import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from src.orchestrator import Orchestrator


def _text_response(text: str, finish_reason: str = "stop", prompt_tokens=100, completion_tokens=50):
    response = MagicMock()
    message = MagicMock()
    message.role = "assistant"
    message.content = text
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return response


def _tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "call_01",
                       prompt_tokens=100, completion_tokens=50):
    response = MagicMock()
    message = MagicMock()
    message.role = "assistant"
    message.content = None
    tc = MagicMock()
    tc.id = tool_id
    tc.function = MagicMock()
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_input)
    message.tool_calls = [tc]
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "tool_calls"
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return response


VALID_JSON = '{"answer": "42", "citations": [], "confidence": 0.9}'


class TestSpanRecording:
    async def test_direct_answer_records_spans(self):
        from src.orchestrator import RunContext

        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(VALID_JSON, prompt_tokens=200, completion_tokens=80)
        )

        ctx = RunContext(question="What is 42?")
        ctx = await orchestrator._step(ctx)  # PLAN
        assert len(ctx.span_records) == 1
        assert ctx.span_records[0].step_type == "plan"
        assert ctx.span_records[0].tokens_in == 200
        assert ctx.span_records[0].tokens_out == 80

    async def test_tool_use_records_tool_span(self):
        from src.tools.calculator import CalculatorTool
        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_tool_use_response("calculator", {"expression": "2+3"})
        )

        from src.orchestrator import RunContext
        ctx = RunContext(question="What is 2+3?")
        ctx = await orchestrator._step(ctx)  # PLAN -> SELECT_TOOL
        ctx = await orchestrator._step(ctx)  # SELECT_TOOL -> CALL_TOOL
        ctx = await orchestrator._step(ctx)  # CALL_TOOL -> OBSERVE

        tool_spans = [s for s in ctx.span_records if s.step_type == "tool_call"]
        assert len(tool_spans) == 1
        assert tool_spans[0].tool_name == "calculator"
        assert tool_spans[0].tokens_in == 0
        assert tool_spans[0].tokens_out == 0

    async def test_observe_records_span_with_tokens(self):
        from src.tools.calculator import CalculatorTool
        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _tool_use_response("calculator", {"expression": "2+3"}, prompt_tokens=150, completion_tokens=30),
                _text_response(VALID_JSON, prompt_tokens=300, completion_tokens=60),
            ]
        )

        from src.orchestrator import RunContext
        ctx = RunContext(question="What is 2+3?")
        ctx = await orchestrator._step(ctx)  # PLAN
        ctx.steps += 1
        ctx = await orchestrator._step(ctx)  # SELECT_TOOL
        ctx.steps += 1
        ctx = await orchestrator._step(ctx)  # CALL_TOOL
        ctx.steps += 1
        ctx = await orchestrator._step(ctx)  # OBSERVE

        observe_spans = [s for s in ctx.span_records if s.step_type == "observe"]
        assert len(observe_spans) == 1
        assert observe_spans[0].tokens_in == 300
        assert observe_spans[0].tokens_out == 60


class TestCostAccumulation:
    async def test_total_cost_accumulates(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(VALID_JSON, prompt_tokens=1000, completion_tokens=500)
        )

        from src.orchestrator import RunContext
        ctx = RunContext(question="test")
        ctx = await orchestrator._step(ctx)  # PLAN
        assert ctx.total_cost > Decimal("0")

    async def test_tool_calls_have_zero_llm_cost(self):
        from src.tools.calculator import CalculatorTool
        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_tool_use_response("calculator", {"expression": "1+1"})
        )

        from src.orchestrator import RunContext
        ctx = RunContext(question="test")
        ctx = await orchestrator._step(ctx)  # PLAN
        ctx.steps += 1
        ctx = await orchestrator._step(ctx)  # SELECT_TOOL
        ctx.steps += 1
        ctx = await orchestrator._step(ctx)  # CALL_TOOL

        tool_spans = [s for s in ctx.span_records if s.step_type == "tool_call"]
        for ts in tool_spans:
            assert ts.cost_usd == Decimal("0")

    async def test_no_usage_yields_zero_cost(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        response = MagicMock()
        message = MagicMock()
        message.role = "assistant"
        message.content = VALID_JSON
        message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = "stop"
        response.choices = [choice]
        response.usage = None

        orchestrator.client.chat.completions.create = AsyncMock(return_value=response)

        from src.orchestrator import RunContext
        ctx = RunContext(question="test")
        ctx = await orchestrator._step(ctx)
        assert ctx.span_records[0].tokens_in == 0
        assert ctx.span_records[0].tokens_out == 0
        assert ctx.total_cost == Decimal("0")


class TestExtractUsage:
    def test_extracts_from_response(self):
        response = MagicMock()
        response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
        assert Orchestrator._extract_usage(response) == (100, 50)

    def test_handles_none_usage(self):
        response = MagicMock()
        response.usage = None
        assert Orchestrator._extract_usage(response) == (0, 0)
