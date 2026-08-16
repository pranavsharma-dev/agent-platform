import asyncio
import enum
import json
import logging
from dataclasses import dataclass, field

from openai import AsyncOpenAI
from pydantic import ValidationError

from src.config import settings
from src.errors import is_retryable
from src.models import AgentAnswer

logger = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
RETRY_BASE_DELAY = 1.0


class OrchestratorError(Exception):
    pass


class State(enum.Enum):
    PLAN = "plan"
    SELECT_TOOL = "select_tool"
    CALL_TOOL = "call_tool"
    OBSERVE = "observe"
    FINALIZE = "finalize"
    ERROR = "error"
    COMPLETE = "complete"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class RunContext:
    question: str
    messages: list = field(default_factory=list)
    state: State = State.PLAN
    current_response: object = None
    pending_tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    steps: int = 0
    answer: AgentAnswer | None = None
    error: str | None = None


SYSTEM_PROMPT = """\
You are a research assistant that answers questions accurately.
You have access to tools. Use them when the question requires calculation or lookup.

When you have gathered enough information, respond with your final answer as a JSON object:
{
    "answer": "your clear, complete answer",
    "citations": [],
    "confidence": 0.9
}

Rules:
- "answer": a clear string answering the question
- "citations": list of {"source": "...", "text": "..."} objects (empty list if none)
- "confidence": float between 0.0 and 1.0
- Your final message must contain ONLY the JSON object, no other text\
"""


class Orchestrator:
    def __init__(self, tools: dict | None = None):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.tools = tools or {}
        self.tool_schemas = [tool.schema() for tool in self.tools.values()]

    async def run(self, question: str) -> AgentAnswer:
        ctx = RunContext(question=question)
        max_steps = settings.max_orchestrator_steps

        while ctx.state not in (State.COMPLETE, State.ERROR):
            if ctx.steps >= max_steps:
                ctx.state = State.ERROR
                ctx.error = f"Exceeded maximum steps ({max_steps})"
                break

            old_state = ctx.state
            ctx = await self._step(ctx)
            logger.info("step %d: %s -> %s", ctx.steps, old_state.value, ctx.state.value)
            ctx.steps += 1

        if ctx.state == State.ERROR:
            raise OrchestratorError(ctx.error)

        return ctx.answer

    async def _step(self, ctx: RunContext) -> RunContext:
        match ctx.state:
            case State.PLAN:
                return await self._plan(ctx)
            case State.SELECT_TOOL:
                return self._select_tool(ctx)
            case State.CALL_TOOL:
                return await self._call_tool(ctx)
            case State.OBSERVE:
                return await self._observe(ctx)
            case State.FINALIZE:
                return await self._finalize(ctx)
            case _:
                ctx.state = State.ERROR
                ctx.error = f"Unexpected state: {ctx.state}"
                return ctx

    # -- State handlers --

    async def _plan(self, ctx: RunContext) -> RunContext:
        ctx.messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": ctx.question},
        ]
        response = await self._call_llm(ctx.messages)
        ctx.current_response = response
        self._append_assistant(ctx, response)

        if response.choices[0].finish_reason == "tool_calls":
            ctx.state = State.SELECT_TOOL
        else:
            ctx.state = State.FINALIZE
        return ctx

    def _select_tool(self, ctx: RunContext) -> RunContext:
        msg = ctx.current_response.choices[0].message
        tool_calls = []
        for tc in msg.tool_calls:
            tool_calls.append(
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                )
            )
        ctx.pending_tool_calls = tool_calls
        ctx.state = State.CALL_TOOL
        return ctx

    async def _call_tool(self, ctx: RunContext) -> RunContext:
        results = []
        for tc in ctx.pending_tool_calls:
            tool = self.tools.get(tc.name)
            if tool is None:
                results.append(
                    ToolResult(
                        tool_use_id=tc.id,
                        content=f"Unknown tool: {tc.name}",
                        is_error=True,
                    )
                )
                continue
            try:
                result = await tool(tc.input)
                results.append(ToolResult(tool_use_id=tc.id, content=str(result)))
            except Exception as e:
                results.append(
                    ToolResult(
                        tool_use_id=tc.id,
                        content=f"Tool execution error: {e}",
                        is_error=True,
                    )
                )
        ctx.tool_results = results
        ctx.state = State.OBSERVE
        return ctx

    async def _observe(self, ctx: RunContext) -> RunContext:
        for r in ctx.tool_results:
            ctx.messages.append({
                "role": "tool",
                "tool_call_id": r.tool_use_id,
                "content": r.content,
            })

        response = await self._call_llm(ctx.messages)
        ctx.current_response = response
        self._append_assistant(ctx, response)

        if response.choices[0].finish_reason == "tool_calls":
            ctx.state = State.SELECT_TOOL
        else:
            ctx.state = State.FINALIZE
        return ctx

    async def _finalize(self, ctx: RunContext) -> RunContext:
        text = self._extract_text(ctx.current_response)

        try:
            json_str = self._extract_json(text)
            data = json.loads(json_str)
            ctx.answer = AgentAnswer(**data)
            ctx.state = State.COMPLETE
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            ctx = await self._repair_output(ctx, text, e)
        return ctx

    async def _repair_output(self, ctx: RunContext, original_text: str, error: Exception) -> RunContext:
        logger.warning("structured output failed, attempting repair: %s", error)
        ctx.messages.append({
            "role": "user",
            "content": (
                f"Your previous response could not be parsed. Error:\n{error}\n\n"
                "Please respond with ONLY a valid JSON object matching this schema:\n"
                '{"answer": "string", "citations": [{"source": "string", "text": "string"}], "confidence": float 0.0-1.0}'
            ),
        })

        try:
            response = await self._call_llm(ctx.messages)
            ctx.current_response = response
            self._append_assistant(ctx, response)
            text = self._extract_text(response)
            json_str = self._extract_json(text)
            data = json.loads(json_str)
            ctx.answer = AgentAnswer(**data)
            ctx.state = State.COMPLETE
        except (json.JSONDecodeError, ValidationError, ValueError, Exception) as repair_error:
            ctx.state = State.ERROR
            ctx.error = f"Failed to parse structured answer after repair attempt: {repair_error}"
        return ctx

    # -- Helpers --

    async def _call_llm(self, messages: list):
        kwargs = {
            "model": settings.model_name,
            "max_tokens": 1024,
            "messages": messages,
        }
        if self.tool_schemas:
            kwargs["tools"] = self.tool_schemas

        last_error = None
        for attempt in range(MAX_LLM_RETRIES):
            try:
                return await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                last_error = e
                if not is_retryable(e):
                    raise
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "LLM call failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1, MAX_LLM_RETRIES, delay, e,
                )
                await asyncio.sleep(delay)

        raise last_error

    @staticmethod
    def _append_assistant(ctx: RunContext, response) -> None:
        msg = response.choices[0].message
        entry: dict = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        ctx.messages.append(entry)

    @staticmethod
    def _extract_text(response) -> str:
        content = response.choices[0].message.content
        return content or ""

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.strip()

        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            return text[start:end].strip()

        if "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            candidate = text[start:end].strip()
            if candidate.startswith("{"):
                return candidate

        brace_start = text.find("{")
        if brace_start >= 0:
            depth = 0
            for i in range(brace_start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return text[brace_start : i + 1]

        return text
