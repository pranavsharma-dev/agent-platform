import enum
import json
import logging
from dataclasses import dataclass, field

import anthropic
from pydantic import ValidationError

from src.config import settings
from src.models import AgentAnswer

logger = logging.getLogger(__name__)


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
        self.client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
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
                return self._finalize(ctx)
            case _:
                ctx.state = State.ERROR
                ctx.error = f"Unexpected state: {ctx.state}"
                return ctx

    # -- State handlers --

    async def _plan(self, ctx: RunContext) -> RunContext:
        ctx.messages = [{"role": "user", "content": ctx.question}]
        response = await self._call_llm(ctx.messages)
        ctx.current_response = response
        ctx.messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            ctx.state = State.SELECT_TOOL
        else:
            ctx.state = State.FINALIZE
        return ctx

    def _select_tool(self, ctx: RunContext) -> RunContext:
        tool_calls = []
        for block in ctx.current_response.content:
            if block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=block.input)
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
                result = await tool.execute(tc.input)
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
        tool_result_blocks = []
        for r in ctx.tool_results:
            block = {
                "type": "tool_result",
                "tool_use_id": r.tool_use_id,
                "content": r.content,
            }
            if r.is_error:
                block["is_error"] = True
            tool_result_blocks.append(block)

        ctx.messages.append({"role": "user", "content": tool_result_blocks})
        response = await self._call_llm(ctx.messages)
        ctx.current_response = response
        ctx.messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "tool_use":
            ctx.state = State.SELECT_TOOL
        else:
            ctx.state = State.FINALIZE
        return ctx

    def _finalize(self, ctx: RunContext) -> RunContext:
        text = self._extract_text(ctx.current_response)

        try:
            json_str = self._extract_json(text)
            data = json.loads(json_str)
            ctx.answer = AgentAnswer(**data)
            ctx.state = State.COMPLETE
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            ctx.state = State.ERROR
            ctx.error = f"Failed to parse structured answer: {e}"
        return ctx

    # -- Helpers --

    async def _call_llm(self, messages: list) -> anthropic.types.Message:
        return await self.client.messages.create(
            model=settings.model_name,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=self.tool_schemas if self.tool_schemas else anthropic.NOT_GIVEN,
            messages=messages,
        )

    @staticmethod
    def _extract_text(response) -> str:
        parts = []
        for block in response.content:
            if block.type == "text":
                parts.append(block.text)
        return "\n".join(parts)

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
