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
