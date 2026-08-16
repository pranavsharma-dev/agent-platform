# Development Log

## Phase 1 — 2026-08-15

### Session 1: Project Scaffolding

**What happened:**
- Set up project structure: docker-compose (Postgres 16, Redis 7, FastAPI app), Dockerfile, requirements, config
- Built the orchestrator as an explicit state machine with 7 states (PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE, ERROR, COMPLETE)
- Implemented calculator tool with AST-based safe evaluator (no eval())
- Created Pydantic models: AgentAnswer (answer, citations, confidence), RunRequest, RunResponse
- Built asyncpg database layer with connection pooling
- Created FastAPI endpoints: POST /run, GET /runs/{id}, GET /health
- Wrote 37 tests: calculator unit tests, orchestrator state machine tests (with mocked LLM), API endpoint tests

**Technical observations:**
- The orchestrator state machine maps cleanly to the OpenAI function-calling API flow: when `finish_reason == "tool_calls"`, transition to SELECT_TOOL; when `finish_reason == "stop"`, transition to FINALIZE
- JSON extraction from LLM text responses needs to handle multiple formats: raw JSON, markdown code blocks, JSON embedded in text. Implemented a brace-depth-tracking parser for robustness
- pytest-asyncio with `asyncio_mode = "auto"` handles async test functions automatically — no need for explicit `@pytest.mark.asyncio` decorators
- Docker Desktop was not running during initial development; all tests run without Docker by mocking the database layer

**Decisions made:**
- Explicit state machine over framework (see DECISION_LOG.md)
- AST-based calculator over eval() (see DECISION_LOG.md)
- OpenAI SDK over Anthropic (see DECISION_LOG.md)
- asyncpg over SQLAlchemy (see DECISION_LOG.md)

**Test results:**
37/37 tests passed. All tests use mocked LLM and database — no external service dependencies for unit tests.

## Phase 2 — 2026-08-15

### Session 1: Tool Registry + Retries + Output Repair

**What happened:**
- Created BaseTool abstract base class with Pydantic input validation — tools define an `input_model()`, and `__call__` validates input before calling `execute()`
- Refactored CalculatorTool to inherit from BaseTool; all existing tests still pass
- Built WebSearchTool as a deterministic stub with canned results for 5 query categories (Python, ML, OTel, FastAPI, France population). Partial matching and case-insensitive
- Built DocLookupTool for keyword-based retrieval over 4 local documents (data/docs/). Scores documents by keyword overlap, returns the best-matching chunk
- Created error classification module (src/errors.py) — classifies OpenAI SDK exceptions as retryable (timeout, rate limit, connection error, HTTP 5xx) or non-retryable (HTTP 4xx, validation errors)
- Added retry wrapper to orchestrator's _call_llm — exponential backoff (1s, 2s, 4s), max 3 attempts, only retries retryable errors
- Added structured output repair to _finalize — on Pydantic validation failure, feeds the error message back to the LLM and retries once
- Created tool registry (build_tool_map()) so main.py no longer manually wires tools
- Wrote 36 new tests covering all Phase 2 features

**Technical observations:**
- Making _finalize async was necessary for the output repair flow — it now calls _call_llm for the repair attempt
- Pydantic's model_json_schema() generates JSON Schema compatible with OpenAI's function-calling format out of the box
- The broad `except Exception` in _repair_output catches both Pydantic validation errors and any LLM call failures during repair, keeping the repair from crashing the orchestrator
- asyncio.sleep in the retry loop needed to be patched in tests to avoid real delays

**Decisions made:**
- BaseTool with Pydantic input models (see DECISION_LOG.md)
- Deterministic stub for web search (see DECISION_LOG.md)
- Exponential backoff with error classification (see DECISION_LOG.md)
- Structured output repair with LLM feedback (see DECISION_LOG.md)

**Test results:**
74/74 tests passed (38 existing + 36 new). All tests use mocked LLM and database.

## Phase 3 — 2026-08-16

### Session 1: Tracing + Cost Ledger

**What happened:**
- Created `spans` table in Postgres with columns: id, run_id, step_index, step_type, tool_name, input_json, output_json, tokens_in, tokens_out, cost_usd, cache_hit, latency_ms, started_at, ended_at. Added index on run_id.
- Built `src/pricing.py` — static pricing table mapping model names to per-token input/output costs using Python Decimal for exact financial arithmetic. Covers gpt-4o-mini and gpt-4o (plus dated variants).
- Added `SpanRecord` Pydantic model and `CostBreakdown` response model to `models.py`. Extended `RunResponse` with `total_cost_usd` and `spans` fields.
- Added DB functions: `insert_span()`, `get_spans()`, `update_run_cost()`
- Instrumented the orchestrator with OpenTelemetry spans — every state handler (_plan, _call_tool, _observe, _finalize, _repair_output) now records timing, token counts, and cost into `SpanData` records on `RunContext`
- Added `_extract_usage()` static method to pull prompt_tokens/completion_tokens from OpenAI response objects
- Orchestrator.run() now accepts optional `run_id` parameter — when provided, persists all spans to Postgres and updates `runs.total_cost_usd` after the loop completes
- Enhanced `GET /runs/{id}` to include full trace (list of spans)
- Added `GET /runs/{id}/cost` endpoint returning cost breakdown with per-span details and aggregate token counts
- Wrote 17 new tests: 6 pricing tests, 8 tracing tests (span recording, cost accumulation, usage extraction), 3 API tests (spans in response, cost endpoint, cost 404)
- Updated all existing API test mocks to include `get_spans` and `update_run_cost` patches

**Technical observations:**
- OpenAI response objects already include `usage.prompt_tokens` and `usage.completion_tokens` — no estimation needed, just extraction
- Using Python `Decimal` for cost calculations avoids floating-point rounding errors that would accumulate across hundreds of eval runs
- `time.perf_counter()` for latency measurement is more precise than `time.time()` — it's a monotonic clock not affected by system time changes
- The existing test mocks already had `response.usage = MagicMock(prompt_tokens=100, completion_tokens=50)` — the mock pattern anticipated Phase 3
- OTel spans wrap each handler for distributed tracing compatibility, while SpanData records capture the same data for Postgres persistence — the two paths are independent so we're not coupled to OTel for our own trace storage
- Tool call spans have zero LLM cost (no tokens) but non-zero latency — important distinction for cost attribution

**Decisions made:**
- OpenTelemetry over custom logging (see DECISION_LOG.md)
- Postgres span persistence over OTel Collector (see DECISION_LOG.md)
- Static pricing table over API lookup (see DECISION_LOG.md)

**Test results:**
91/91 tests passed (74 existing + 17 new). All tests use mocked LLM and database.
