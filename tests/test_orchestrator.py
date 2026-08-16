import json

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from openai import APITimeoutError

from src.models import AgentAnswer
from src.orchestrator import Orchestrator, OrchestratorError, State, RunContext


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


class TestRetry:
    @patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock)
    async def test_retries_on_timeout_then_succeeds(self, mock_sleep):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        timeout_err = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                timeout_err,
                _text_response(VALID_JSON_ANSWER),
            ]
        )

        result = await orchestrator.run("test")
        assert result.answer == "The result is 42"
        assert orchestrator.client.chat.completions.create.call_count == 2
        mock_sleep.assert_called_once()

    @patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock)
    async def test_gives_up_after_max_retries(self, mock_sleep):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        timeout_err = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=timeout_err
        )

        with pytest.raises(APITimeoutError):
            await orchestrator.run("test")
        assert orchestrator.client.chat.completions.create.call_count == 3

    @patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock)
    async def test_does_not_retry_non_retryable(self, mock_sleep):
        from openai import APIStatusError

        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        mock_response = httpx.Response(
            status_code=400,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        )
        bad_request_err = APIStatusError(
            message="Bad request", response=mock_response, body=None
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=bad_request_err
        )

        with pytest.raises(APIStatusError):
            await orchestrator.run("test")
        assert orchestrator.client.chat.completions.create.call_count == 1
        mock_sleep.assert_not_called()

    @patch("src.orchestrator.asyncio.sleep", new_callable=AsyncMock)
    async def test_exponential_backoff_delays(self, mock_sleep):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        timeout_err = APITimeoutError(
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        )
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                timeout_err,
                timeout_err,
                _text_response(VALID_JSON_ANSWER),
            ]
        )

        await orchestrator.run("test")
        delays = [call.args[0] for call in mock_sleep.call_args_list]
        assert delays[0] == 1.0
        assert delays[1] == 2.0


class TestStructuredOutputRepair:
    async def test_repairs_bad_confidence(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        bad_json = '{"answer": "test", "citations": [], "confidence": 5.0}'
        fixed_json = '{"answer": "test", "citations": [], "confidence": 0.9}'
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _text_response(bad_json),
                _text_response(fixed_json),
            ]
        )

        result = await orchestrator.run("test")
        assert result.confidence == 0.9
        assert orchestrator.client.chat.completions.create.call_count == 2

    async def test_repair_failure_raises_error(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        bad_json = '{"answer": "test", "citations": [], "confidence": 5.0}'
        still_bad = '{"answer": "test", "citations": [], "confidence": 10.0}'
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _text_response(bad_json),
                _text_response(still_bad),
            ]
        )

        with pytest.raises(OrchestratorError, match="repair attempt"):
            await orchestrator.run("test")

    async def test_repairs_invalid_json(self):
        orchestrator = Orchestrator(tools={})
        orchestrator.client = MagicMock()
        orchestrator.client.chat = MagicMock()
        orchestrator.client.chat.completions = MagicMock()

        fixed_json = '{"answer": "42", "citations": [], "confidence": 0.9}'
        orchestrator.client.chat.completions.create = AsyncMock(
            side_effect=[
                _text_response("I think the answer is 42"),
                _text_response(fixed_json),
            ]
        )

        result = await orchestrator.run("test")
        assert result.answer == "42"


class TestExtractJson:
    def test_handles_braces_inside_string_values(self):
        text = '{"answer": "Use {braces} like {this}", "citations": [], "confidence": 0.9}'
        result = Orchestrator._extract_json(text)
        parsed = json.loads(result)
        assert parsed["answer"] == "Use {braces} like {this}"

    def test_handles_escaped_quotes_in_strings(self):
        text = r'{"answer": "He said \"hello {world}\"", "citations": [], "confidence": 0.8}'
        result = Orchestrator._extract_json(text)
        parsed = json.loads(result)
        assert parsed["confidence"] == 0.8

    def test_handles_nested_json_objects(self):
        text = '{"answer": "test", "citations": [{"source": "a", "text": "b"}], "confidence": 0.7}'
        result = Orchestrator._extract_json(text)
        parsed = json.loads(result)
        assert len(parsed["citations"]) == 1
