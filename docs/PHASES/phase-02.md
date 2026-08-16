# Phase 2 Complete — Tool Registry + Retries + Structured Output Repair

## 1. What We Built

Tool system with a base abstraction, three tools, retry logic with error classification, and structured output repair.

Components:
- **BaseTool** abstract base class with Pydantic input validation
- **CalculatorTool** refactored to inherit from BaseTool
- **WebSearchTool** — deterministic stub with canned results for eval reliability
- **DocLookupTool** — keyword-based retrieval over local text documents
- **Tool registry** — `build_tool_map()` replaces manual tool wiring
- **Error classification** — `is_retryable()` checks OpenAI exception hierarchy
- **Retry wrapper** — exponential backoff (1s, 2s, 4s) on `_call_llm`, max 3 attempts
- **Structured output repair** — feeds Pydantic validation errors back to LLM, retries once
- **74 passing tests** (38 existing + 36 new)

## 2. Files Changed

```
src/tools/base.py          # NEW — BaseTool ABC
src/tools/calculator.py    # MODIFIED — inherits BaseTool, Pydantic input model
src/tools/web_search.py    # NEW — deterministic stub
src/tools/doc_lookup.py    # NEW — local document retrieval
src/tools/__init__.py      # MODIFIED — tool registry
src/errors.py              # NEW — error classification
src/orchestrator.py        # MODIFIED — retry wrapper, output repair
src/main.py                # MODIFIED — uses build_tool_map()
data/docs/python_overview.txt       # NEW — document corpus
data/docs/opentelemetry_basics.txt  # NEW
data/docs/fastapi_guide.txt         # NEW
data/docs/postgresql_essentials.txt # NEW
tests/test_web_search.py       # NEW — 6 tests
tests/test_doc_lookup.py       # NEW — 8 tests
tests/test_errors.py           # NEW — 12 tests
tests/test_tool_registry.py    # NEW — 3 tests
tests/test_calculator.py       # MODIFIED — uses __call__, added validation test
tests/test_orchestrator.py     # MODIFIED — added retry + repair tests
docs/ARCHITECTURE.md           # UPDATED
docs/DECISION_LOG.md           # UPDATED — 5 new decisions
docs/DEVELOPMENT_LOG.md        # UPDATED
docs/INTERVIEW_GUIDE.md        # UPDATED
docs/TRADEOFFS.md              # UPDATED — 2 new tradeoffs
docs/PROJECT.md                # UPDATED
docs/GLOSSARY.md               # UPDATED
docs/PHASES/phase-02.md        # NEW — this file
```

## 3. Architecture

```
POST /run → FastAPI → Orchestrator State Machine → GPT-4o-mini (with retry)
                 ↓                                        ↓
            PostgreSQL                          Tool Registry
                                               ├── Calculator (AST)
                                               ├── Web Search (stub)
                                               └── Doc Lookup (local)

FINALIZE → Pydantic Validation
              ├── valid → COMPLETE
              └── invalid → Output Repair (feed error → LLM retry)
                               ├── valid → COMPLETE
                               └── still invalid → ERROR
```

## 4. Important Decisions

1. **BaseTool with Pydantic input models** — validation before execute, schema from model
2. **Deterministic web search stub** — eval reliability over realism
3. **Custom exponential backoff** — transparent, no library dependency
4. **Error classification** — retryable vs non-retryable based on OpenAI exception hierarchy
5. **Output repair with error feedback** — feed specific Pydantic error back to LLM

See docs/DECISION_LOG.md for full details.

## 5. Problems Encountered

No blocking problems in this phase. The _finalize method needed to become async to support the repair flow (calls _call_llm for the retry), which was a straightforward change.

## 6. Tests and Verification

**74/74 tests passed.**

| Suite | Tests | Coverage |
|-------|-------|----------|
| Calculator (safe_eval) | 13 | All operators, error cases, injection attempts |
| Calculator (tool) | 5 | Schema, execute via __call__, validation |
| Web Search | 6 | Known queries, partial match, unknown, case sensitivity, validation |
| Doc Lookup | 8 | Each document, no match, empty corpus, validation |
| Error Classification | 12 | All error types (timeout, rate limit, connection, 5xx, 4xx, generic) |
| Tool Registry | 3 | All tools present, BaseTool instances, valid schemas |
| Orchestrator (direct answer) | 2 | No tools, JSON in code block |
| Orchestrator (with tools) | 3 | Single tool call, unknown tool, sequential calls |
| Orchestrator (errors) | 3 | Invalid JSON, invalid confidence, max steps |
| Orchestrator (state transitions) | 2 | Direct path, tool-use path |
| Orchestrator (retry) | 4 | Retry then succeed, max retries, no retry on 400, backoff delays |
| Orchestrator (output repair) | 3 | Repairs bad confidence, repair failure, repairs invalid JSON |
| API | 7 | Health, run, get run |
| **Total** | **74** | |

All tests use mocked LLM (no API calls) and mocked database (no Postgres needed).

**Not verified:**
- End-to-end with real OpenAI API (requires OPENAI_API_KEY)
- Docker Compose startup (requires Docker Desktop)

## 7. Limitations

- No tracing — runs are not inspectable beyond the database record
- No cost tracking — token usage is not recorded
- No caching — every run makes fresh LLM calls
- Web search returns only canned results (by design for eval)
- Doc lookup uses simple keyword matching, not semantic search
- No jitter on retry backoff (acceptable for single-client agent)

## 8. Interview Questions I Should Know

1. "Why did you create a base tool abstraction?" — consistency, validation, schema generation
2. "Why are the search results stubbed?" — eval reliability, cost, reproducibility
3. "Walk me through what happens when the LLM returns confidence: 5.0" — Pydantic catches, feeds error back, LLM retries
4. "How does your retry policy work?" — exponential backoff, error classification, max 3
5. "Why exponential backoff?" — gives struggling services progressively more recovery time
6. "Why not use tenacity?" — 15 lines of code, fully visible, no dependency to explain
7. "How do you classify retryable vs non-retryable errors?" — is_retryable() checks OpenAI exception types
8. "What happens if the output repair also fails?" — run fails with error, capped at one retry

## 9. Interview-Ready Explanations

**Tool System:**
"Every tool extends BaseTool, which defines the contract: an input Pydantic model, a schema() that generates OpenAI function-calling format, and execute() for the actual logic. The __call__ method validates input through Pydantic before calling execute, so tool implementations can't receive invalid data. Adding a new tool means writing a class and adding it to one list in the registry."

**Error Classification:**
"I classify OpenAI SDK exceptions into two buckets. Retryable: timeouts, rate limits, connection errors, and HTTP 5xx — these are transient and may succeed on retry. Non-retryable: HTTP 4xx (except 429, which is rate limiting) — bad request, auth failure, not found. The retry wrapper only retries the first category. This prevents wasting money retrying errors that will never succeed."

**Structured Output Repair:**
"When the LLM's final answer fails Pydantic validation — say confidence is 5.0 instead of between 0 and 1 — I don't just fail the run. I append the specific Pydantic error to the conversation and call the LLM again. It now has the full context plus the exact validation error, so it can fix the issue. One retry, specific feedback. If the repair also fails, then the run fails. The cost of the retry is one extra LLM call — about a tenth of a cent with GPT-4o-mini."

## 10. Genuine Stories From This Phase

- Making `_finalize` async was the only structural change needed to support the repair flow — the state machine design from Phase 1 accommodated the new feature cleanly.
- Pydantic's `model_json_schema()` generates JSON Schema that is directly compatible with OpenAI's function-calling format — no manual schema maintenance needed.
- The `asyncio.sleep` in the retry loop had to be mocked in tests to avoid real delays — a standard testing pattern but worth noting.

## 11. What I Personally Need to Understand

### Must know
- How BaseTool.__call__ validates input then delegates to execute()
- How Pydantic model_json_schema() generates OpenAI function schemas
- Error classification logic: which exceptions are retryable and why
- The structured output repair flow: catch → feedback → retry → validate
- Why web_search is stubbed (eval reliability argument)

### Should know
- How exponential backoff math works (delay = base * 2^attempt)
- OpenAI SDK exception hierarchy (APITimeoutError, RateLimitError, APIStatusError)
- How the doc_lookup keyword scoring works
- Python ABC mechanics (@abstractmethod, @property)

### Nice to know
- How the web search partial matching works (substring check both directions)
- How _find_relevant_chunk selects the best passage from a document
- tenacity library features (for comparison)

## 12. Documentation Updated

- docs/ARCHITECTURE.md — updated to Phase 2 state
- docs/DECISION_LOG.md — 5 new decisions added
- docs/DEVELOPMENT_LOG.md — Phase 2 session recorded
- docs/TRADEOFFS.md — 2 new tradeoffs added
- docs/INTERVIEW_GUIDE.md — Phase 2 questions and knowledge checklist
- docs/PROJECT.md — status updated
- docs/GLOSSARY.md — 6 terms updated from "(Phase 2)" placeholders to actual definitions

## 13. Recommended Git Commit

```
feat: add tool registry, retry with backoff, and structured output repair

BaseTool ABC with Pydantic input validation, web_search deterministic
stub, doc_lookup over local documents, tool registry. Exponential
backoff retry (max 3) with retryable/non-retryable error classification.
Structured output repair feeds Pydantic errors back to LLM. 74 tests.
```

## 14. What Comes Next

**Phase 3** will add:
- OpenTelemetry SDK spans for every orchestrator step
- Span attributes: step type, tool name, tokens in/out, latency, cache hit/miss
- Persist spans to PostgreSQL (spans table)
- Static pricing table, per-step cost calculation
- GET /runs/{id} returns full trace, GET /runs/{id}/cost returns cost breakdown
