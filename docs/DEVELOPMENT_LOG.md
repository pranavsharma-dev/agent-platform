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

## Phase 4 — 2026-08-16

### Session 1: Content-Hash Cache

**What happened:**
- Created `src/cache.py` — async Redis client with connection pool, SHA-256 cache key generation, get/set with configurable TTL (default 1 hour), graceful degradation on Redis errors
- Added `CachedResponse` dataclass to orchestrator — serializable representation of an LLM response for cache storage
- Integrated cache checking into all three LLM-calling handlers: `_plan`, `_observe`, `_repair_output`. Before each LLM call, compute cache key → check Redis → on hit, reconstruct response from cached data with cost=$0; on miss, call LLM and store result
- Added `_serialize_response()` and `_build_mock_response()` helpers to convert between OpenAI response objects and cache-storable dicts
- Wired `cache.init_redis()` / `cache.close_redis()` into FastAPI lifespan
- Added `redis[hiredis]>=5.0.0` to requirements.txt
- Created verification script (`scripts/verify_cache.py`) that runs the same question twice and shows cost reduction on second run
- Wrote 23 new tests covering cache key generation, get/set, serialization, and cache integration with the orchestrator

**Pre-phase fixes:**
- Fixed `fail_run()` to actually persist error messages (was silently dropping the error parameter)
- Fixed `_extract_json()` brace-matching to handle braces inside JSON string values
- Added `error_message` column to runs table schema

**Technical observations:**
- Using `MagicMock` to reconstruct cached responses works but isn't typed — the mock quacks like an OpenAI response object because the orchestrator only accesses `.choices[0].message.content`, `.tool_calls`, `.finish_reason`, and `.usage`
- Cache key normalization via `json.dumps(sort_keys=True, separators=(",", ":"))` ensures key-order-independent, whitespace-independent hashing
- Existing tests pass without modification because `cache_get` returns None when `_pool` is None (no Redis connection) — automatic cache-miss behavior
- `redis[hiredis]` uses the C-accelerated hiredis parser for better performance — the `[hiredis]` extra installs it automatically

**Decisions made:**
- Content-hash cache in Redis (see DECISION_LOG.md)
- Cache at step level, not run level (see DECISION_LOG.md)
- Graceful degradation on cache failure (see DECISION_LOG.md)

**Test results:**
117/117 tests passed (94 existing + 23 new). All tests use mocked LLM, database, and Redis.

## Phase 4 — 2026-08-16

### Session 2: Post-Audit Fixes

**What happened:**
- Ran a 20-step self-audit against the Phase 4 implementation. Found 2 real bugs and 2 tech debt items.
- Fixed stuck-run bug: broadened `POST /run` except clause from `OrchestratorError` to `Exception`. Runs no longer get stuck at `status='running'` when raw OpenAI SDK exceptions propagate. Added `logger.exception()` for visibility.
- Fixed token double-counting: cache-hit spans now report `tokens_in=0, tokens_out=0` instead of historical values from the original run. `CostBreakdown.total_tokens_in/out` now reflects actual API usage.
- Added `.dockerignore` to prevent `.env`, `.git`, `__pycache__`, tests, and docs from being baked into Docker images.
- Consolidated three duplicate cache-check blocks into `_cached_llm_call()` helper method — one function returns `(response, tokens_in, tokens_out, hit)`.
- Added regression test `test_raw_exception_still_fails_run` — raises `AuthenticationError` from orchestrator, asserts response is `status='failed'` (not HTTP 500).
- Removed now-unused `OrchestratorError` import from `main.py`.

**Technical observations:**
- The self-audit caught a bug (stuck runs) that had existed since Phase 1 but was masked by tests that only ever mocked `OrchestratorError`. The test suite passed 117/117 while the bug was live — a concrete example of how mocking at the wrong level can give false confidence.
- `logger.exception()` at the API boundary is important — it preserves the full traceback including the original SDK exception type, which would be lost if we only stored `str(e)` in the database.

**Decisions made:**
- Broad exception handling at API boundary (see DECISION_LOG.md)
- Consolidate cache logic into helper (see DECISION_LOG.md)
- Zero tokens on cache-hit spans (see DECISION_LOG.md)

**Test results:**
118/118 tests passed (117 existing + 1 new).
