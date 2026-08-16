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
