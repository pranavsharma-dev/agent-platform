import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.models import AgentAnswer
from src.orchestrator import Orchestrator, OrchestratorError, State


def _text_response(text: str, finish_reason: str = "stop"):
    """Mock an OpenAI ChatCompletion response with text content."""
    response = MagicMock()
    message = MagicMock()
    message.role = "assistant"
    message.content = text
    message.tool_calls = None
    choice = MagicMock()
    choice.message = message
    choice.finish_reason = finish_reason
    response.choices = [choice]
    response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return response


def _tool_use_response(tool_name: str, tool_input: dict, tool_id: str = "call_01"):
    """Mock an OpenAI ChatCompletion response with a tool call."""
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
    response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return response


VALID_JSON_ANSWER = '{"answer": "The result is 42", "citations": [], "confidence": 0.95}'


class TestOrchestratorDirectAnswer:
    async def test_returns_answer_without_tools(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(VALID_JSON_ANSWER)
        )

        result = await orchestrator.run("What is the meaning of life?")
        assert isinstance(result, AgentAnswer)
        assert result.answer == "The result is 42"
        assert result.confidence == 0.95
        assert result.citations == []

    async def test_handles_json_in_code_block(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(f"```json\n{VALID_JSON_ANSWER}\n```")
        )

        result = await orchestrator.run("test")
        assert result.answer == "The result is 42"


class TestOrchestratorWithTools:
    async def test_uses_calculator_then_answers(self):
        from src.tools.calculator import CalculatorTool

        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = (
            '{"answer": "25 times 47 is 1175", "citations": [], "confidence": 0.99}'
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _tool_use_response("calculator", {"expression": "25 * 47"}),
                _text_response(answer_json),
            ]
        )

        result = await orchestrator.run("What is 25 times 47?")
        assert result.answer == "25 times 47 is 1175"
        assert result.confidence == 0.99

        assert orchestrator.client.chat.completions.create.call_count == 2

    async def test_handles_unknown_tool(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = (
            '{"answer": "I could not compute that", "citations": [], "confidence": 0.3}'
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _tool_use_response("nonexistent", {"x": 1}),
                _text_response(answer_json),
            ]
        )

        result = await orchestrator.run("test")
        assert result.confidence == 0.3

    async def test_multiple_tool_calls_in_sequence(self):
        from src.tools.calculator import CalculatorTool

        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = '{"answer": "Sum is 30", "citations": [], "confidence": 0.95}'
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _tool_use_response("calculator", {"expression": "10 + 5"}, "c1"),
                _tool_use_response("calculator", {"expression": "15 + 15"}, "c2"),
                _text_response(answer_json),
            ]
        )

        result = await orchestrator.run("What is 10+5, then add 15?")
        assert result.answer == "Sum is 30"
        assert orchestrator.client.chat.completions.create.call_count == 3


class TestOrchestratorErrors:
    async def test_invalid_json_raises_error(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response("This is not JSON at all")
        )

        with pytest.raises(OrchestratorError, match="Failed to parse"):
            await orchestrator.run("test")

    async def test_invalid_confidence_raises_error(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        bad_json = '{"answer": "test", "citations": [], "confidence": 5.0}'
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(bad_json)
        )

        with pytest.raises(OrchestratorError, match="Failed to parse"):
            await orchestrator.run("test")

    async def test_max_steps_exceeded(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_tool_use_response("calculator", {"expression": "1+1"})
        )

        from src.config import settings

        original = settings.max_orchestrator_steps
        settings.max_orchestrator_steps = 2
        try:
            with pytest.raises(OrchestratorError, match="Exceeded maximum steps"):
                await orchestrator.run("infinite loop")
        finally:
            settings.max_orchestrator_steps = original


class TestStateTransitions:
    async def test_direct_answer_transitions(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()
        orchestrator.client.chat.completions.create = AsyncMock(
            return_value=_text_response(VALID_JSON_ANSWER)
        )

        from src.orchestrator import RunContext

        ctx = RunContext(question="test")
        assert ctx.state == State.PLAN

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.FINALIZE

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.COMPLETE

    async def test_tool_use_transitions(self):
        from src.tools.calculator import CalculatorTool

        calculator = CalculatorTool()
        orchestrator = Orchestrator(tools={"calculator": calculator})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        answer_json = '{"answer": "5", "citations": [], "confidence": 0.9}'
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _tool_use_response("calculator", {"expression": "2+3"}),
                _text_response(answer_json),
            ]
        )

        from src.orchestrator import RunContext

        ctx = RunContext(question="test")
        assert ctx.state == State.PLAN

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.SELECT_TOOL

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.CALL_TOOL

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.OBSERVE

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.FINALIZE

        ctx = await orchestrator._step(ctx)
        assert ctx.state == State.COMPLETE
