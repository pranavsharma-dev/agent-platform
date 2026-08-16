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
| "tool-calling" | Calculator, web_search, doc_lookup via BaseTool registry | `src/tools/` |
| "retries" | Exponential backoff (1s, 2s, 4s), error classification | `src/orchestrator.py`, `src/errors.py` |
| "structured outputs" | Pydantic AgentAnswer + output repair (feed error back to LLM) | `src/models.py`, `src/orchestrator.py` |
| "per-step tracing" | OTel spans + SpanData per state handler | `src/orchestrator.py` |
| "token/cost accounting" | Static pricing table, Decimal arithmetic | `src/pricing.py` |
| "inspectable" | GET /runs/{id} returns full trace with spans | `src/main.py` |
| "attributable" | GET /runs/{id}/cost returns per-span cost breakdown | `src/main.py` |

## Resume Bullet 2 Defense

> Shipped a regression-eval harness — versioned eval sets, deterministic graders plus an LLM judge calibrated against human labels — wired into CI to gate merges, catching quality and cost regressions before release; a content-hash cache cuts repeat-call cost on unchanged steps.

| Phrase | Implementation | File |
|--------|----------------|------|
| "content-hash cache" | SHA-256 of (step_type + normalized_input) | `src/cache.py` |
| "cuts repeat-call cost" | Cache hit → cost = $0, LLM not called | `src/orchestrator.py` |
| "on unchanged steps" | Same step + same input = same key = hit | `src/cache.py`, `src/orchestrator.py` |

*(Remaining phrases to be completed in Phases 5–7)*

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

## Interview Questions — Phase 2

### Tool System

**Q: Why did you create a base tool abstraction?**

*Strong answer:* "Consistency and safety. Every tool follows the same contract: define an input Pydantic model, implement execute(). The base class __call__ validates input before execute() runs — tools can't receive invalid data. And schema() generates the OpenAI function schema directly from the Pydantic model, so there's one source of truth for what a tool accepts."

---

**Q: Why are the search results stubbed instead of hitting a real API?**

*Strong answer:* "Evaluation reliability. The eval harness in Phase 5 needs reproducible inputs to detect quality regressions. If search results change between runs, I can't tell if a regression came from my code or from different search data. The stub gives me deterministic inputs so the eval isolates agent behavior. The tool interface is identical — swapping in a real API is a single class change."

---

### Retry and Error Handling

**Q: How does your retry policy work?**

*Strong answer:* "Exponential backoff — 1 second, 2 seconds, 4 seconds — max 3 attempts. But only for retryable errors: timeouts, rate limits, connection errors, and HTTP 5xx. Non-retryable errors like bad request (400) or auth failure (401) raise immediately. The error classification is explicit — is_retryable() checks the OpenAI SDK's exception hierarchy."

*Follow-up: "Why exponential and not linear?"*

*Answer:* "Linear backoff hammers a struggling service at a constant rate. Exponential gives the service progressively more breathing room to recover. It's the standard approach for rate-limited APIs."

---

**Q: Walk me through what happens when the LLM returns confidence: 5.0.**

*Strong answer:* "Pydantic catches it — confidence has a ge=0.0, le=1.0 constraint. Instead of failing the run, the orchestrator sends a repair message: 'Your response couldn't be parsed. Error: confidence must be ≤ 1.0. Please respond with only a valid JSON object.' The LLM gets the original conversation plus the specific error, so it can fix the exact issue. If the repair also fails, the run fails. One retry, specific feedback, capped cost."

---

## What I Must Personally Know (Phase 1 + Phase 2)

### Must know
- What a state machine is and why the orchestrator uses one
- How each state (PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE) works
- How OpenAI's function-calling API works (tool schemas, tool_calls, tool role messages)
- How Pydantic validates the agent's answer
- Why eval() is dangerous and how the AST parser avoids the risk
- The request lifecycle from POST /run to response
- How the BaseTool abstraction works — __call__ validates, execute() runs
- How error classification decides what to retry
- How structured output repair feeds the error back to the LLM
- Why web_search is stubbed (eval reliability)

### Should know
- How asyncpg connection pooling works
- How the JSON extraction handles markdown code blocks and embedded JSON
- How pytest-asyncio handles async tests
- How the max_steps guard prevents infinite loops
- How exponential backoff math works (delay = base * 2^attempt)
- OpenAI SDK exception hierarchy (APITimeoutError, RateLimitError, APIStatusError)
- How Pydantic model_json_schema() generates OpenAI-compatible function schemas

### Nice to know
- Python AST module internals
- asyncpg vs psycopg comparison
- OpenAI API rate limiting behavior
- Python ABC mechanics (@abstractmethod, @property)

---

## Interview Questions — Phase 3

### Tracing

**Q: How do you make agent runs observable?**

*What the interviewer is testing:* Do you understand observability beyond logging?

*Strong answer:* "Every orchestrator step — plan, tool_call, observe, finalize — creates two things: an OpenTelemetry span for distributed tracing compatibility, and a SpanData record that I persist to Postgres. Each span captures step_type, tokens_in, tokens_out, cost_usd, latency_ms, and timestamps. GET /runs/{id} returns the full trace — you can see exactly what the agent did, in what order, how long each step took, and what it cost."

---

**Q: Why OpenTelemetry instead of just structured logging?**

*Strong answer:* "Structured logs give me searchable events, but not parent-child relationships. OTel gives me spans with context propagation — the root span is the agent run, each step is a child. I get a trace tree with timing. I also persist spans to Postgres for API access, so I have both the OTel standard and queryable SQL storage."

---

**Q: Why persist spans to Postgres instead of using Jaeger?**

*Strong answer:* "The API is the interface. GET /runs/{id} returns spans alongside the run record. Jaeger would require another service and give me a separate UI, but the traces need to be programmatically accessible for the CI gate in Phase 7. SQL also lets me aggregate — cost by tool type, average latency by step, slowest runs. Adding a Jaeger exporter later is one line of config."

---

### Cost Accounting

**Q: How do you track cost per run?**

*Strong answer:* "After each LLM call, I extract prompt_tokens and completion_tokens from the OpenAI response's usage field. I multiply by the model's per-token price from a static pricing table — Decimal arithmetic to avoid floating-point drift. Each span records its own cost_usd, and the total accumulates on the run record. GET /runs/{id}/cost returns the per-span breakdown."

---

**Q: Why Decimal instead of float for cost?**

*Strong answer:* "The CI gate in Phase 7 compares costs between eval runs — a 15% increase fails the build. With float, rounding drift across hundreds of cases could trigger false positives or mask real regressions. Decimal gives exact arithmetic from the pricing table through aggregation."

---

**Q: What happens when OpenAI changes their prices?**

*Strong answer:* "I update two lines in the pricing dict and redeploy. OpenAI has no pricing API, so I can't fetch current prices at runtime. The table only includes models I actually use. Unknown models return zero cost rather than erroring — this is a deliberate choice so a model name change doesn't crash the agent."

---

## What I Must Personally Know (Phase 3)

### Must know
- What an OTel span is and how parent/child relationships work
- How token counts are extracted from OpenAI responses (usage.prompt_tokens, usage.completion_tokens)
- How cost is calculated (tokens × price / 1M, Decimal arithmetic)
- The spans table schema and what each column stores
- How to explain the trace for a typical run (plan → tool_call → observe → finalize)
- Why Postgres over Jaeger for span storage
- Why Decimal over float for cost

### Should know
- The difference between opentelemetry-api and opentelemetry-sdk
- How time.perf_counter() differs from time.time()
- How OTel exporters work (console, OTLP, Jaeger)
- How span attributes are set and queried
- The cost difference between GPT-4o-mini and GPT-4o ($0.15/M vs $2.50/M input)

---

## Interview Questions — Phase 4

### Caching

**Q: How does the cache work?**

*What the interviewer is testing:* Do you understand content-addressable caching and can you explain the key generation strategy?

*Strong answer:* "Before each LLM call, I compute a SHA-256 hash of the step type plus the normalized input — JSON.dumps with sorted keys so key order doesn't matter. I check Redis for that key. On a hit, I reconstruct the response from cached data and skip the API call entirely — cost is zero. On a miss, I call the LLM, serialize the response, and store it with a 1-hour TTL. If Redis is down, cache_get returns None and the agent runs normally."

---

**Q: Why cache at the step level instead of caching the whole run?**

*Strong answer:* "Partial reuse. A multi-step run might share the plan step with a previous run but diverge at the observe step — maybe the tool returned slightly different results. Step-level caching saves the plan call's cost even when later steps differ. Run-level is all-or-nothing."

---

**Q: What happens if Redis goes down?**

*What the interviewer is testing:* Resilience design, failure modes.

*Strong answer:* "The agent keeps running. cache_get catches any exception, logs a warning, and returns None — which is treated as a cache miss. cache_set fails silently. Every run costs more because we call the LLM every time, but no runs fail. The cache is a cost optimization, not a correctness dependency."

---

**Q: How do you normalize the cache input?**

*Strong answer:* "json.dumps with sort_keys=True and compact separators. This ensures that {'a': 1, 'b': 2} and {'b': 2, 'a': 1} produce the same hash. The step_type is prepended to prevent collisions — a plan step and an observe step with the same messages get different cache keys."

---

**Q: Why Redis instead of an in-memory cache?**

*Strong answer:* "Redis was already in the docker-compose stack. It gives me TTL-based expiration, persistence across process restarts, and would work across multiple app instances. The ~1ms roundtrip is negligible compared to a ~500ms LLM call."

---

## What I Must Personally Know (Phase 4)

### Must know
- How the cache key is generated (SHA-256 of step_type + normalized JSON)
- What gets cached (LLM responses) and what doesn't (tool calls, parsing)
- The cache flow: check → hit/miss → reconstruct or store
- Why step-level over run-level (partial reuse)
- Why Redis over in-memory (TTL, restarts, multi-instance)
- What graceful degradation means and why the cache isn't a correctness dependency
- How cache_hit=True on a span means cost=$0

### Should know
- How json.dumps sort_keys=True ensures deterministic serialization
- How SHA-256 properties (deterministic, collision-resistant) make it suitable for cache keys
- How the mock response is reconstructed from cached data
- Redis TTL behavior (key expires, next access is a miss)
- The hiredis C extension and why it's used (performance)
- Why the tool-call ID doesn't break cache correctness across runs
- Why cache-hit spans report zero tokens (reconciles with real API billing)

---

## Interview Questions — Post-Audit Fixes

### Error Handling

**Q: What happens if the OpenAI API key is wrong or rate-limited?**

*What the interviewer is testing:* Do you understand your system's failure modes? Can you be honest about gaps you found and fixed?

*Strong answer:* "The retry logic classifies AuthenticationError as non-retryable and raises immediately. The API handler catches it with a broad except Exception, logs the full traceback, marks the run as failed with the error message, and returns a clean JSON response. I found this gap during a self-audit — originally the handler only caught my own OrchestratorError type, which meant raw SDK exceptions left runs stuck at 'running' forever with no error message. I confirmed it by running the stack with a bad API key and checking the database row."

*Follow-up:* "How did you find this bug?"

*Answer:* "I traced the full POST /run failure path by hand during a Phase 4 audit, then reproduced it live against the real Docker stack. The run row was stuck at status='running' with error_message=NULL. All 117 tests passed while this bug existed — because the test for failed runs only mocked OrchestratorError, never a raw SDK exception. That's a concrete example of how mocking at the wrong level gives false confidence."

---

**Q: Why catch Exception instead of just OrchestratorError?**

*Strong answer:* "The API boundary is the last line of defense — a stuck run with no error message is worse than a broadly-caught exception. I log the full traceback with logger.exception(), so no diagnostic information is lost. The alternative — wrapping every _call_llm raise in OrchestratorError — would hide the original exception type in logs. At this scale, the broad catch is simpler and more resilient."

---

### Cache Subtleties

**Q: Walk me through why the tool-call ID from a previous run doesn't break the cache on the next run.**

*What the interviewer is testing:* Do you understand the non-obvious correctness properties of your cache design?

*Strong answer:* "When the plan step hits cache, I reconstruct a mock response carrying the exact tool-call ID that was cached. That ID flows unchanged through _select_tool, gets attached to the tool result in _call_tool, and ends up in ctx.messages for the observe step in the same shape as the original run. Since the observe cache key is a hash of the full messages list, and that list is now byte-identical to the original, the observe step also hits cache. I verified this with an integration test using a real in-memory Redis stand-in, not just mocked cache_get."

*Follow-up:* "What if a tool returns non-deterministic results?"

*Answer:* "The observe step's cache key naturally changes because the tool result text differs — clean cache miss, not a wrong answer. The content-hash approach fails safe: worst case is more LLM calls, never stale answers."

---

**Q: Does your token count reconcile with OpenAI billing?**

*Strong answer:* "Yes. Cache-hit spans report zero tokens because no API call was made. Originally I stored the historical token counts from the first run, which inflated the aggregate. I caught that in a self-audit and fixed it — the CostBreakdown now accurately reflects real API token consumption."
