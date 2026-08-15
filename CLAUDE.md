# Agent Platform — Project Context

## What This Is

Infrastructure platform around a multi-step AI research agent. The agent answers questions using tools (search, calculator, doc lookup) and produces structured cited answers. The **platform** — not the agent — is the project: observability, evaluation, cost tracking, caching, and CI/CD infrastructure for an AI agent.

Two equally important goals:
1. Build a technically strong backend/AI-infrastructure project whose resume claims are literally supported by the implementation.
2. The developer (Pranav) must personally understand and defend every component in a software engineering interview.

## Resume Claims (Source of Truth)

Every design decision must trace back to one of these:

> **Bullet 1:** Built an orchestration layer for a multi-step LLM agent (tool-calling, retries, structured outputs) with per-step tracing and token/cost accounting, so every run is inspectable and attributable rather than a black box.

> **Bullet 2:** Shipped a regression-eval harness — versioned eval sets, deterministic graders plus an LLM judge calibrated against human labels — wired into CI to gate merges, catching quality and cost regressions before release; a content-hash cache cuts repeat-call cost on unchanged steps.

If a feature doesn't trace back to one of these sentences, cut it.

## Tech Stack (Decided)

| Layer          | Choice                          |
|----------------|---------------------------------|
| Language       | Python 3.12 (compatible 3.11+)  |
| API            | FastAPI                         |
| Database       | PostgreSQL 16                   |
| Cache          | Redis 7                         |
| Tracing        | OpenTelemetry SDK               |
| LLM            | **OpenAI SDK**                  |
| Agent model    | GPT-4o-mini (`gpt-4o-mini`)     |
| Judge model    | GPT-4o (`gpt-4o`) — Phase 5+    |
| Containers     | Docker + Compose                |
| CI             | GitHub Actions                  |
| Validation     | Pydantic v2                     |
| DB driver      | asyncpg (raw SQL, no ORM)       |

**LLM provider decision:** OpenAI SDK chosen for lowest API cost (GPT-4o-mini is ~5x cheaper per token than Claude Haiku). Tool calling uses OpenAI's `tool_calls` / function-calling format.

## Non-Negotiable Rules

1. **ONE phase at a time.** Never implement future phases. Stop after each phase is complete.
2. **Specification is source of truth.** Don't casually change architecture, tech stack, scope, or resume claims.
3. **Never fabricate** evaluation scores, benchmark results, cache savings, latency improvements, bugs, failures, interview stories, or performance numbers. If a number is needed, build the mechanism that measures it.
4. **Optimize for interview defensibility.** Prefer implementations Pranav can understand and defend. Don't hide behavior behind frameworks.
5. **No scope creep.** Don't add features, refactor, or introduce abstractions beyond what the task requires.
6. **No unnecessary dependencies.** Explain why before introducing any new dependency.
7. **Never commit secrets.** Use environment variables. Provide `.env.example`.

## Current State

### Phase 1 — COMPLETE ✓
Skeleton with working orchestrator, calculator tool, validated structured output, Postgres persistence.

**37/37 tests passing** (mocked LLM and DB — no external services needed for tests).

### What Exists

```
agent-platform/
├── CLAUDE.md                    # This file
├── .gitignore
├── .env.example
├── docker-compose.yml           # Postgres 16, Redis 7, app
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── db/
│   └── init.sql                 # runs table
├── src/
│   ├── __init__.py
│   ├── config.py                # pydantic-settings, env-based
│   ├── models.py                # AgentAnswer, Citation, RunRequest, RunResponse, RunStatus
│   ├── db.py                    # asyncpg pool, create/complete/fail/get run
│   ├── orchestrator.py          # ★ Explicit state machine (PLAN→SELECT_TOOL→CALL_TOOL→OBSERVE→FINALIZE)
│   ├── main.py                  # FastAPI: POST /run, GET /runs/{id}, GET /health
│   └── tools/
│       ├── __init__.py
│       └── calculator.py        # AST-based safe_eval, CalculatorTool class
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # no_db fixture
│   ├── test_calculator.py       # 17 tests
│   ├── test_orchestrator.py     # 10 tests (mocked LLM)
│   └── test_api.py              # 7 tests (mocked DB + orchestrator)
└── docs/
    ├── PROJECT.md
    ├── ARCHITECTURE.md
    ├── DECISION_LOG.md           # 4 decisions documented
    ├── DEVELOPMENT_LOG.md
    ├── FAILURE_LOG.md
    ├── TRADEOFFS.md              # 3 tradeoffs documented
    ├── GLOSSARY.md
    ├── INTERVIEW_GUIDE.md
    └── PHASES/
        └── phase-01.md
```

### Key Architectural Decisions Made

1. **Explicit state machine** over LangChain — for observability, testability, traceable step transitions
2. **AST-based calculator** over eval() — LLM controls input, eval() is code injection
3. **OpenAI SDK** over Anthropic — cheapest API cost (GPT-4o-mini ~5x cheaper per token)
4. **asyncpg raw SQL** over SQLAlchemy — small schema (≤6 tables), every query visible

### Database Schema (Current)

```sql
runs(id UUID PK, created_at TIMESTAMPTZ, input_question TEXT, final_answer JSONB, status TEXT, total_cost_usd NUMERIC)
```

### Planned Schema (Future Phases)

```sql
spans(id, run_id, step_type, tool_name, input_json, output_json, tokens_in, tokens_out, cost_usd, cache_hit, latency_ms, started_at, ended_at)
eval_runs(id, git_sha, created_at, aggregate_score, aggregate_cost_usd, passed)
eval_case_results(id, eval_run_id, case_id, deterministic_score, judge_score, passed)
judge_calibration(id, eval_case_result_id, human_label, judge_label, agree)
```

## Remaining Phases

### Phase 2 — Tool Registry + Retries + Structured Output
- Base Tool abstraction with JSON schema validation
- web_search tool (deterministic stub for eval reliability)
- doc_lookup tool (simple local retrieval over fixed documents)
- Retry wrapper: exponential backoff, max 3 attempts
- Error classification: retryable (timeout, rate limit) vs non-retryable (bad schema, invalid request)
- Structured output repair: feed Pydantic validation error back to LLM, retry once

### Phase 3 — Tracing + Cost Ledger
- OpenTelemetry SDK spans for every orchestrator step (plan, tool call, LLM call)
- Span attributes: step type, tool name, tokens in/out, latency, cache hit/miss
- Persist spans to PostgreSQL (spans table)
- Static pricing table, per-step cost calculation
- GET /runs/{id} returns full trace, GET /runs/{id}/cost returns cost breakdown

### Phase 4 — Content-Hash Cache
- SHA-256 of (step_type + normalized_input) → Redis key
- Cache hit: skip call, return cached output, cost = $0
- Cache miss: execute, store result, TTL = 1 hour
- Verification script: same input twice, second run costs less

### Phase 5 — Eval Harness
- Versioned dataset: evals/v1/cases.yaml (50–100 cases, created by Pranav)
- Eval runner: runs agent on each case
- Deterministic graders: exact match, citation validation, schema check
- LLM judge: GPT-4o scores correctness + groundedness on 1–5 rubric
- Results stored in Postgres, aggregate score + cost

### Phase 6 — Judge Calibration
- Pranav manually labels ~30–50 judge outputs
- Calculate agreement rate and Cohen's kappa
- Analyze disagreements
- Makes "calibrated against human labels" defensible

### Phase 7 — CI Gate
- GitHub Actions workflow: docker-compose up → health check → run evals → compare to baseline.json
- Fail on quality drop > 5% or cost increase > 15%
- Create intentional regression, show CI catching it

### Phase 8 — Polish for Defensibility
- README, architecture diagram, setup instructions
- Trace walkthrough, eval walkthrough, CI walkthrough
- docker-compose up + one command runs everything
- Final interview guide with 50–100 questions

## Documentation Structure

Maintain progressively — don't fabricate future content:

```
docs/
├── PROJECT.md           # What, why, status, resume claims
├── ARCHITECTURE.md      # Current architecture with Mermaid diagrams
├── DECISION_LOG.md      # Every significant decision with interview Q&A
├── DEVELOPMENT_LOG.md   # Chronological record of real events
├── FAILURE_LOG.md       # Real failures only
├── TRADEOFFS.md         # Major tradeoffs with interview Q&A
├── GLOSSARY.md          # Project-specific term definitions
├── INTERVIEW_GUIDE.md   # Pitches, walkthroughs, question bank
└── PHASES/phase-XX.md   # Phase completion reports (14-section template)
```

## Phase Completion Requirements

Every phase must end with:
- Working implementation + tests
- Documentation updates (decision log, dev log, architecture, interview guide)
- Phase report (14 sections — see docs/PHASES/phase-01.md for template)
- Recommended git commit
- STOP — do not continue to next phase

## Scope Cuts (Do NOT Build)

- Multi-agent communication / agent-to-agent
- Fine-tuning / custom models
- Fancy frontend (minimal HTML or CLI is enough)
- Production authentication / multi-tenancy
- Per-tenant token budgets

## Running the Project

```bash
# Tests (no Docker needed)
pip install -r requirements.txt
python -m pytest tests/ -v

# Full stack
docker compose up
# Then: POST http://localhost:8000/run with {"question": "What is 25 * 47?"}

# Requires .env with OPENAI_API_KEY for real LLM calls
```
