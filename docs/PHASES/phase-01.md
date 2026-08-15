# Phase 1 Complete — Skeleton & One Working Tool Call

## 1. What We Built

A working end-to-end pipeline: question → orchestrator → LLM → optional tool call → validated structured answer → Postgres.

Components:
- **FastAPI app** with POST /run, GET /runs/{id}, GET /health
- **Orchestrator** as an explicit state machine (PLAN → SELECT_TOOL → CALL_TOOL → OBSERVE → FINALIZE)
- **Calculator tool** with AST-based safe expression evaluator
- **Pydantic models** for AgentAnswer (answer, citations, confidence)
- **asyncpg database layer** with connection pooling and CRUD operations
- **Docker Compose** with Postgres 16, Redis 7, and the app service
- **37 passing tests** covering calculator, orchestrator, and API

## 2. Files Changed

```
.gitignore
.env.example
requirements.txt
pyproject.toml
docker-compose.yml
Dockerfile
db/init.sql
src/__init__.py
src/config.py
src/models.py
src/db.py
src/orchestrator.py
src/main.py
src/tools/__init__.py
src/tools/calculator.py
tests/__init__.py
tests/conftest.py
tests/test_calculator.py
tests/test_orchestrator.py
tests/test_api.py
docs/PROJECT.md
docs/ARCHITECTURE.md
docs/DECISION_LOG.md
docs/DEVELOPMENT_LOG.md
docs/FAILURE_LOG.md
docs/TRADEOFFS.md
docs/GLOSSARY.md
docs/INTERVIEW_GUIDE.md
docs/PHASES/phase-01.md
```

## 3. Architecture

```
POST /run → FastAPI → Orchestrator State Machine → GPT-4o-mini → Calculator Tool
                 ↓                                                              ↓
            PostgreSQL (runs table)                                    safe_eval (AST)
```

State machine flow: PLAN → (SELECT_TOOL → CALL_TOOL → OBSERVE)* → FINALIZE → COMPLETE

## 4. Important Decisions

1. **Explicit state machine** over LangChain — for observability and testability
2. **AST-based calculator** over eval() — for security
3. **OpenAI SDK** over Anthropic — cheapest API cost (GPT-4o-mini ~5x cheaper per token)
4. **asyncpg** over SQLAlchemy — minimal abstraction for a small schema

See docs/DECISION_LOG.md for full details.

## 5. Problems Encountered

- **Docker Desktop not running**: docker-compose could not start during development. All tests are designed to run without Docker (mocked DB layer), so development was not blocked. Docker verification deferred to when Docker Desktop is started.

## 6. Tests and Verification

**37/37 tests passed.**

| Suite | Tests | Coverage |
|-------|-------|----------|
| Calculator (safe_eval) | 13 | All operators, error cases, injection attempts |
| Calculator (tool) | 4 | Schema, execute, error handling |
| Orchestrator (direct answer) | 2 | No tools, JSON in code block |
| Orchestrator (with tools) | 3 | Single tool call, unknown tool, sequential calls |
| Orchestrator (errors) | 3 | Invalid JSON, invalid confidence, max steps |
| Orchestrator (state transitions) | 2 | Direct path, tool-use path |
| API (health) | 1 | GET /health |
| API (run) | 4 | Success, run_id, failure, validation |
| API (get run) | 2 | Existing, nonexistent |
| **Total** | **37** | |

All tests use mocked LLM (no API calls) and mocked database (no Postgres needed).

**Not verified:**
- End-to-end with real OpenAI API (requires OPENAI_API_KEY)
- Docker Compose startup (requires Docker Desktop)

## 7. Limitations

- No retries — LLM failures crash the run
- No structured output repair — validation failure = run failure
- No tracing — runs are not inspectable beyond the database record
- No cost tracking — token usage is not recorded
- No caching — every run makes fresh LLM calls
- Only one tool (calculator)
- JSON extraction from LLM text is heuristic — could fail on unusual formats

## 8. Interview Questions I Should Know

1. "Walk me through the request lifecycle" — trace POST /run through all states
2. "Why an explicit state machine?" — observability, testability, traceability
3. "Why not LangChain?" — framework hides the loop; I need step-level visibility
4. "How does the calculator work? Why not eval()?" — AST parsing, security
5. "Why OpenAI over Anthropic?" — cheapest API cost, mature function-calling
6. "Why asyncpg over SQLAlchemy?" — small schema, visible queries, fastest driver
7. "What happens if the LLM returns invalid JSON?" — OrchestratorError (Phase 2 adds retry)
8. "How do you prevent infinite loops?" — max_steps guard

## 9. Interview-Ready Explanations

**Orchestrator:**
"I chose an explicit state machine because I wanted the agent's control flow to be observable. Instead of letting a framework hide the loop, I made PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, and FINALIZE explicit states. Each transition gets logged. In Phase 3, each one becomes an OpenTelemetry span. I can write tests that assert the exact sequence of state transitions."

**Calculator:**
"The LLM controls the expression string, so eval() is a code injection risk. I parse the expression into a Python AST and only walk arithmetic nodes — constants, binary operators like add/multiply, unary operators like negation. Anything else raises a ValueError. Secure by construction."

**Structured output:**
"The final answer is a Pydantic model: answer string, citations list, confidence float between 0 and 1. The LLM is instructed to output JSON. I parse it and validate with Pydantic. If confidence is 5.0 — out of range — Pydantic catches it. Right now a validation failure fails the run; Phase 2 adds a retry with the error message fed back to the LLM."

## 10. Genuine Stories From This Phase

- **Docker Desktop not running**: Discovered during the verify step. Rather than blocking, all tests were already designed to mock the database layer. This validated that the test architecture is independent of infrastructure — a useful observation for interview discussions about test isolation.

## 11. What I Personally Need to Understand

### Must know
- The 7 orchestrator states and what each does
- How OpenAI's function-calling API works: tool schemas → tool_calls → tool role messages
- How Pydantic validates the AgentAnswer schema
- Why eval() is dangerous and how AST parsing avoids it
- The request lifecycle from POST /run to response
- How mocking the LLM client enables deterministic tests

### Should know
- How asyncpg connection pooling works
- How the JSON extractor handles code blocks and embedded JSON (brace-depth tracking)
- How FastAPI's lifespan context manager initializes/closes the DB pool
- How pytest-asyncio auto mode works

### Nice to know
- Python ast module internals (ast.parse, node types)
- Pydantic v2 model_dump() vs v1 dict()
- asyncpg's prepared statement caching

## 12. Documentation Updated

- docs/PROJECT.md — created
- docs/ARCHITECTURE.md — created
- docs/DECISION_LOG.md — 4 decisions documented
- docs/DEVELOPMENT_LOG.md — Phase 1 session recorded
- docs/FAILURE_LOG.md — created (empty, no real failures)
- docs/TRADEOFFS.md — 3 tradeoffs documented
- docs/GLOSSARY.md — all terms defined
- docs/INTERVIEW_GUIDE.md — pitches, walkthrough, question bank started

## 13. Recommended Git Commit

```
feat: add explicit agent orchestration loop with calculator tool

Bare orchestrator state machine (PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE,
FINALIZE), AST-based calculator tool, Pydantic structured output
validation, FastAPI endpoints, asyncpg Postgres layer, Docker Compose
stack. 37 tests passing.
```

## 14. What Comes Next

**Phase 2** will add:
- Tool registry with base Tool abstraction
- web_search and doc_lookup tools
- Retry wrapper with exponential backoff
- Retryable vs non-retryable error classification
- Structured output validation retry (feed error back to LLM)
