# Interview Guide

## 30-Second Explanation

"I built an infrastructure platform around a multi-step AI agent. The agent answers research questions using tools like search and calculation. The platform makes every run observable — I can see each step, which tools were called, how many tokens were used, and what it cost. I also built an evaluation harness with deterministic graders and an LLM judge calibrated against my own labels, wired into CI to catch quality regressions before they ship."

## 1-Minute Explanation

"The core is an orchestrator built as an explicit state machine — PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE — rather than hiding the loop inside a framework. This makes every step traceable. Each step gets an OpenTelemetry span with token counts, latency, and cache status, persisted to Postgres. A cost ledger tracks dollars per step so every run is financially attributable.

For quality, I built an evaluation harness with versioned test cases, deterministic graders for objective checks, and an LLM judge for nuanced quality assessment. I calibrated the judge against my own human labels — about 40 cases — and measured agreement with Cohen's kappa. The eval suite runs in CI via GitHub Actions: if quality drops more than 5% or cost increases more than 15% compared to the baseline, the build fails."

## 3-Minute Architecture Walkthrough

*What to say while drawing the architecture:*

"Start with the API layer. A question comes in via POST /run to a FastAPI gateway. This creates a run record in Postgres and hands the question to the orchestrator.

The orchestrator is an explicit state machine. It starts in PLAN — sends the question to GPT-4o-mini with available tool schemas. The model either requests a tool or produces an answer. If it requests a tool, we go through SELECT_TOOL to parse the request, CALL_TOOL to execute it, and OBSERVE to feed the result back. This loop repeats until the model produces a final answer.

The final answer goes through FINALIZE, where we parse the JSON and validate it with Pydantic — answer string, citations list, confidence float. If validation fails, we retry once with the error message. If it fails again, the run fails.

Every step along this path creates an OpenTelemetry span — plan, tool_call, llm_call — with attributes for tokens, latency, cost, and cache status. These persist to a spans table in Postgres.

Before any LLM or tool call, we check a content-hash cache in Redis. SHA-256 of the step type plus normalized input. On a hit, we skip the call entirely — zero cost, sub-millisecond latency. Misses get stored with a 1-hour TTL.

On the evaluation side: I have a versioned dataset of question/expected-answer cases in YAML, tracked in git. An eval runner feeds each case through the agent, then scores it two ways. Deterministic graders handle objective checks — exact match, citation validation. An LLM judge scores correctness and groundedness on a 1-5 rubric.

I calibrated the judge by manually labeling about 40 outputs and computing agreement rate and Cohen's kappa. This makes 'calibrated against human labels' a defensible claim.

The whole eval suite runs in GitHub Actions. Docker-compose spins up the stack, the runner executes all cases, compares scores to a baseline.json, and fails the build if quality drops more than 5% or cost rises more than 15%."

---

## Resume Bullet 1 Defense

> Built an orchestration layer for a multi-step LLM agent (tool-calling, retries, structured outputs) with per-step tracing and token/cost accounting, so every run is inspectable and attributable rather than a black box.

| Phrase | Implementation | File |
|--------|----------------|------|
| "orchestration layer" | Explicit state machine with 7 states | `src/orchestrator.py` |
| "multi-step LLM agent" | Agent loops through tool calls until answer | `src/orchestrator.py` |
| "tool-calling" | Calculator (+ web_search, doc_lookup in Phase 2) with JSON schemas | `src/tools/` |
| "retries" | *(Phase 2)* Exponential backoff, error classification | |
| "structured outputs" | Pydantic AgentAnswer model (answer, citations, confidence) | `src/models.py` |
| "per-step tracing" | *(Phase 3)* OpenTelemetry spans per state | |
| "token/cost accounting" | *(Phase 3)* Cost ledger: tokens × price per step | |
| "inspectable" | GET /runs/{id} returns full run details | `src/main.py` |
| "attributable" | *(Phase 3)* Per-step cost breakdown | |

## Resume Bullet 2 Defense

> Shipped a regression-eval harness — versioned eval sets, deterministic graders plus an LLM judge calibrated against human labels — wired into CI to gate merges, catching quality and cost regressions before release; a content-hash cache cuts repeat-call cost on unchanged steps.

*(To be completed in Phases 4–7)*

---

## Interview Questions — Phase 1

### Architecture

**Q: Why did you build your own orchestration loop instead of using LangChain?**

*What the interviewer is testing:* Do you understand the tradeoff between using a framework and building from scratch? Can you justify a build-over-buy decision?

*Strong answer:* "Observability is the core value proposition. I needed every state transition to be a traceable, testable event — something I can log, attach an OpenTelemetry span to, and assert in tests. LangChain's AgentExecutor hides the loop. I'd get a faster prototype but lose the step-level visibility that's the whole point. The state machine is more code, but each state handler is a focused 10-line function."

*Likely follow-up:* "When would you use LangChain?"

*Answer:* "For a product prototype where shipping speed matters more than infrastructure visibility. If I don't need per-step tracing or cost attribution, the framework saves real time."

---

**Q: Walk me through what happens when a question comes in.**

*What the interviewer is testing:* Can you trace the request lifecycle through your system?

*Strong answer:* "POST /run hits FastAPI. We create a run record in Postgres with status 'running'. The orchestrator starts in PLAN — sends the question to GPT-4o-mini with tool schemas. The response either has tool_calls (go to SELECT_TOOL → CALL_TOOL → OBSERVE → back to LLM) or a text response (go to FINALIZE). In FINALIZE, I parse the JSON from the text, validate it with Pydantic — answer, citations, confidence — and if valid, update the run record to 'completed' with the answer."

---

**Q: How does the calculator tool work? Why not just use eval()?**

*What the interviewer is testing:* Security awareness, input validation.

*Strong answer:* "The LLM controls the expression string — it's untrusted input. eval() would execute arbitrary Python. I parse the expression into a Python AST and walk it, only allowing constants and arithmetic operators. Anything else — function calls, variable names, imports — raises a ValueError. It's secure by construction rather than trying to sanitize dangerous input."

---

### Why Did You Choose X?

**Q: Why FastAPI?**
"Async-native, built-in request validation via Pydantic, automatic OpenAPI docs. The orchestrator makes async LLM API calls, so an async framework is the natural fit. Flask would work but I'd need to bolt on async support."

**Q: Why PostgreSQL?**
"I need structured relational data — runs, spans, eval results — with JSON support for flexible fields like final_answer. Postgres gives me JSONB, strong typing, and it's the industry standard for this kind of operational data."

**Q: Why Pydantic for structured outputs?**
"It validates and coerces LLM output against a typed schema in one line. If the LLM returns confidence as a string '0.9' instead of a float, Pydantic coerces it. If it returns confidence as 5.0 (out of range), Pydantic rejects it. I get type safety on untrusted LLM output without writing validation logic."

---

## What I Must Personally Know (Phase 1)

### Must know
- What a state machine is and why the orchestrator uses one
- How each state (PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE) works
- How OpenAI's function-calling API works (tool schemas, tool_calls, tool role messages)
- How Pydantic validates the agent's answer
- Why eval() is dangerous and how the AST parser avoids the risk
- The request lifecycle from POST /run to response

### Should know
- How asyncpg connection pooling works
- How the JSON extraction handles markdown code blocks and embedded JSON
- How pytest-asyncio handles async tests
- How the max_steps guard prevents infinite loops

### Nice to know
- Python AST module internals
- asyncpg vs psycopg comparison
- OpenAI API rate limiting behavior
