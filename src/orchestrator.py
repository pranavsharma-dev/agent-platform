import asyncio
import enum
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from openai import AsyncOpenAI
from opentelemetry import trace
from pydantic import ValidationError

from src.cache import cache_get, cache_key, cache_set
from src.config import settings
from src.errors import is_retryable
from src.models import AgentAnswer
from src.pricing import compute_cost

logger = logging.getLogger(__name__)
tracer = trace.get_tracer("agent-platform")

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
class CachedResponse:
    content: str | None
    tool_calls: list[dict] | None
    finish_reason: str
    tokens_in: int
    tokens_out: int


@dataclass
class SpanData:
    step_index: int
    step_type: str
    tool_name: str | None = None
    input_json: dict | None = None
    output_json: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    cache_hit: bool = False
    latency_ms: float = 0.0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


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
    span_records: list[SpanData] = field(default_factory=list)
    total_cost: Decimal = Decimal("0")


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

    async def run(self, question: str, run_id: UUID | None = None) -> AgentAnswer:
        ctx = RunContext(question=question)
        max_steps = settings.max_orchestrator_steps

        with tracer.start_as_current_span("agent_run", attributes={"question": question}) as root_span:
            while ctx.state not in (State.COMPLETE, State.ERROR):
                if ctx.steps >= max_steps:
                    ctx.state = State.ERROR
                    ctx.error = f"Exceeded maximum steps ({max_steps})"
                    break

                old_state = ctx.state
                ctx = await self._step(ctx)
                logger.info("step %d: %s -> %s", ctx.steps, old_state.value, ctx.state.value)
                ctx.steps += 1

            root_span.set_attribute("total_steps", ctx.steps)
            root_span.set_attribute("total_cost_usd", float(ctx.total_cost))
            root_span.set_attribute("status", ctx.state.value)

            if run_id is not None:
                await self._persist_spans(run_id, ctx)

        if ctx.state == State.ERROR:
            raise OrchestratorError(ctx.error)

        return ctx.answer

    async def _persist_spans(self, run_id: UUID, ctx: RunContext) -> None:
        from src import db
        for span_data in ctx.span_records:
            await db.insert_span(
                run_id=run_id,
                step_index=span_data.step_index,
                step_type=span_data.step_type,
                tool_name=span_data.tool_name,
                input_json=span_data.input_json,
                output_json=span_data.output_json,
                tokens_in=span_data.tokens_in,
                tokens_out=span_data.tokens_out,
                cost_usd=span_data.cost_usd,
                cache_hit=span_data.cache_hit,
                latency_ms=span_data.latency_ms,
                started_at=span_data.started_at,
                ended_at=span_data.ended_at,
            )
        await db.update_run_cost(run_id, ctx.total_cost)

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
        with tracer.start_as_current_span("plan") as span:
            started_at = datetime.now(timezone.utc)
            t0 = time.perf_counter()

            ctx.messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": ctx.question},
            ]

            response, tokens_in, tokens_out, hit = await self._cached_llm_call(
                "plan", {"question": ctx.question}, ctx.messages
            )

            ctx.current_response = response
            self._append_assistant(ctx, response)

            latency_ms = (time.perf_counter() - t0) * 1000
            ended_at = datetime.now(timezone.utc)
            cost = Decimal("0") if hit else compute_cost(settings.model_name, tokens_in, tokens_out)

            span.set_attribute("step_type", "plan")
            span.set_attribute("tokens_in", tokens_in)
            span.set_attribute("tokens_out", tokens_out)
            span.set_attribute("cost_usd", float(cost))
            span.set_attribute("latency_ms", latency_ms)
            span.set_attribute("cache_hit", hit)

            ctx.span_records.append(SpanData(
                step_index=ctx.steps,
                step_type="plan",
                input_json={"question": ctx.question},
                output_json={"content": self._extract_text(response)},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                cache_hit=hit,
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=ended_at,
            ))
            ctx.total_cost += cost

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
            with tracer.start_as_current_span(f"tool_{tc.name}") as span:
                started_at = datetime.now(timezone.utc)
                t0 = time.perf_counter()

                tool = self.tools.get(tc.name)
                if tool is None:
                    result = ToolResult(
                        tool_use_id=tc.id,
                        content=f"Unknown tool: {tc.name}",
                        is_error=True,
                    )
                    results.append(result)
                    latency_ms = (time.perf_counter() - t0) * 1000
                    ended_at = datetime.now(timezone.utc)

                    span.set_attribute("step_type", "tool_call")
                    span.set_attribute("tool_name", tc.name)
                    span.set_attribute("error", True)

                    ctx.span_records.append(SpanData(
                        step_index=ctx.steps,
                        step_type="tool_call",
                        tool_name=tc.name,
                        input_json=tc.input,
                        output_json={"error": f"Unknown tool: {tc.name}"},
                        latency_ms=latency_ms,
                        started_at=started_at,
                        ended_at=ended_at,
                    ))
                    continue

                try:
                    output = await tool(tc.input)
                    result = ToolResult(tool_use_id=tc.id, content=str(output))
                except Exception as e:
                    output = f"Tool execution error: {e}"
                    result = ToolResult(
                        tool_use_id=tc.id,
                        content=output,
                        is_error=True,
                    )

                results.append(result)
                latency_ms = (time.perf_counter() - t0) * 1000
                ended_at = datetime.now(timezone.utc)

                span.set_attribute("step_type", "tool_call")
                span.set_attribute("tool_name", tc.name)
                span.set_attribute("latency_ms", latency_ms)

                ctx.span_records.append(SpanData(
                    step_index=ctx.steps,
                    step_type="tool_call",
                    tool_name=tc.name,
                    input_json=tc.input,
                    output_json={"result": result.content, "is_error": result.is_error},
                    latency_ms=latency_ms,
                    started_at=started_at,
                    ended_at=ended_at,
                ))

        ctx.tool_results = results
        ctx.state = State.OBSERVE
        return ctx

    async def _observe(self, ctx: RunContext) -> RunContext:
        with tracer.start_as_current_span("observe") as span:
            started_at = datetime.now(timezone.utc)
            t0 = time.perf_counter()

            for r in ctx.tool_results:
                ctx.messages.append({
                    "role": "tool",
                    "tool_call_id": r.tool_use_id,
                    "content": r.content,
                })

            response, tokens_in, tokens_out, hit = await self._cached_llm_call(
                "observe", {"messages": ctx.messages}, ctx.messages
            )

            ctx.current_response = response
            self._append_assistant(ctx, response)

            latency_ms = (time.perf_counter() - t0) * 1000
            ended_at = datetime.now(timezone.utc)
            cost = Decimal("0") if hit else compute_cost(settings.model_name, tokens_in, tokens_out)

            span.set_attribute("step_type", "observe")
            span.set_attribute("tokens_in", tokens_in)
            span.set_attribute("tokens_out", tokens_out)
            span.set_attribute("cost_usd", float(cost))
            span.set_attribute("latency_ms", latency_ms)
            span.set_attribute("cache_hit", hit)

            ctx.span_records.append(SpanData(
                step_index=ctx.steps,
                step_type="observe",
                input_json={"tool_results": [{"id": r.tool_use_id, "content": r.content} for r in ctx.tool_results]},
                output_json={"content": self._extract_text(response)},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                cache_hit=hit,
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=ended_at,
            ))
            ctx.total_cost += cost

        if response.choices[0].finish_reason == "tool_calls":
            ctx.state = State.SELECT_TOOL
        else:
            ctx.state = State.FINALIZE
        return ctx

    async def _finalize(self, ctx: RunContext) -> RunContext:
        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        text = self._extract_text(ctx.current_response)

        try:
            json_str = self._extract_json(text)
            data = json.loads(json_str)
            ctx.answer = AgentAnswer(**data)
            ctx.state = State.COMPLETE
        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            ctx = await self._repair_output(ctx, text, e)

        latency_ms = (time.perf_counter() - t0) * 1000
        ended_at = datetime.now(timezone.utc)

        ctx.span_records.append(SpanData(
            step_index=ctx.steps,
            step_type="finalize",
            input_json={"raw_text": text},
            output_json={"parsed": ctx.answer.model_dump() if ctx.answer else None},
            latency_ms=latency_ms,
            started_at=started_at,
            ended_at=ended_at,
        ))

        return ctx

    async def _repair_output(self, ctx: RunContext, original_text: str, error: Exception) -> RunContext:
        logger.warning("structured output failed, attempting repair: %s", error)

        started_at = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        ctx.messages.append({
            "role": "user",
            "content": (
                f"Your previous response could not be parsed. Error:\n{error}\n\n"
                "Please respond with ONLY a valid JSON object matching this schema:\n"
                '{"answer": "string", "citations": [{"source": "string", "text": "string"}], "confidence": float 0.0-1.0}'
            ),
        })

        try:
            response, tokens_in, tokens_out, hit = await self._cached_llm_call(
                "repair", {"messages": ctx.messages}, ctx.messages
            )

            ctx.current_response = response
            self._append_assistant(ctx, response)
            text = self._extract_text(response)
            json_str = self._extract_json(text)
            data = json.loads(json_str)
            ctx.answer = AgentAnswer(**data)
            ctx.state = State.COMPLETE

            cost = Decimal("0") if hit else compute_cost(settings.model_name, tokens_in, tokens_out)

            latency_ms = (time.perf_counter() - t0) * 1000
            ended_at = datetime.now(timezone.utc)

            ctx.span_records.append(SpanData(
                step_index=ctx.steps,
                step_type="repair",
                input_json={"original_error": str(error)},
                output_json={"content": text},
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                cache_hit=hit,
                latency_ms=latency_ms,
                started_at=started_at,
                ended_at=ended_at,
            ))
            ctx.total_cost += cost

        except (json.JSONDecodeError, ValidationError, ValueError, Exception) as repair_error:
            ctx.state = State.ERROR
            ctx.error = f"Failed to parse structured answer after repair attempt: {repair_error}"
        return ctx

    # -- Helpers --

    async def _cached_llm_call(
        self, step_type: str, cache_input: dict, messages: list
    ) -> tuple[object, int, int, bool]:
        """Check cache before calling LLM. Returns (response, tokens_in, tokens_out, cache_hit)."""
        key = cache_key(step_type, cache_input)
        cached = await cache_get(key)
        if cached is not None:
            cr = CachedResponse(**cached)
            return self._build_mock_response(cr), 0, 0, True
        response = await self._call_llm(messages)
        tokens_in, tokens_out = self._extract_usage(response)
        await cache_set(key, self._serialize_response(response, tokens_in, tokens_out))
        return response, tokens_in, tokens_out, False

    @staticmethod
    def _serialize_response(response, tokens_in: int, tokens_out: int) -> dict:
        msg = response.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                }
                for tc in msg.tool_calls
            ]
        return {
            "content": msg.content,
            "tool_calls": tool_calls,
            "finish_reason": response.choices[0].finish_reason,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    @staticmethod
    def _build_mock_response(cr: CachedResponse):
        from unittest.mock import MagicMock

        response = MagicMock()
        message = MagicMock()
        message.content = cr.content
        if cr.tool_calls:
            tcs = []
            for tc_data in cr.tool_calls:
                tc = MagicMock()
                tc.id = tc_data["id"]
                tc.function = MagicMock()
                tc.function.name = tc_data["name"]
                tc.function.arguments = tc_data["arguments"]
                tcs.append(tc)
            message.tool_calls = tcs
        else:
            message.tool_calls = None
        choice = MagicMock()
        choice.message = message
        choice.finish_reason = cr.finish_reason
        response.choices = [choice]
        response.usage = MagicMock(
            prompt_tokens=cr.tokens_in,
            completion_tokens=cr.tokens_out,
        )
        return response

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
    def _extract_usage(response) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return usage.prompt_tokens, usage.completion_tokens

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
            in_string = False
            escape_next = False
            for i in range(brace_start, len(text)):
                ch = text[i]
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[brace_start : i + 1]

        return text
