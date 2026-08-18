# Decision Log

## Decision: Explicit State Machine for Orchestrator

### Context
The orchestrator needs to manage a multi-step loop: ask the LLM, possibly call tools, observe results, repeat. We needed to choose how to structure this control flow.

### Options considered
1. **Framework-based** (LangChain, LlamaIndex) — hide the loop inside a library
2. **Simple while loop** — `while not done: call_llm(); if tool: execute()` in flat code
3. **Explicit state machine** — named states (PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE) with typed transitions

### Decision
Explicit state machine with an enum of states and a match/case dispatcher.

### Why
- Every state transition is visible, loggable, and testable
- Maps directly to OpenTelemetry spans
- Each state handler is a focused function
- State transitions can be asserted in tests

### Tradeoffs
- More code than a simple while loop
- Must manually manage state transitions (risk of forgetting an edge case)
- Slightly more complex than necessary for a simple calculator-only agent

### Failure modes
- Infinite loop if a state transition cycles without advancing (mitigated by max_steps)
- State that doesn't match any handler (mitigated by exhaustive match and default error)

---

## Decision: AST-Based Safe Calculator Instead of eval()

### Context
The calculator tool needs to evaluate mathematical expressions from LLM output.

### Options considered
1. **Python `eval()`** — simplest, supports all Python math
2. **AST parsing** — parse the expression as an AST, walk it, only allow arithmetic nodes
3. **Third-party library** (sympy, numexpr)

### Decision
AST-based safe evaluator using Python's `ast` module.

### Why
- `eval()` is a code injection vulnerability — the LLM controls the input string
- AST parsing lets us whitelist exactly which operations are allowed
- No external dependency needed

### Tradeoffs
- More code than `eval()`
- Limited to basic arithmetic (no functions like sqrt, sin)
- Need to handle each operator explicitly

### Failure modes
- Missing operator in the whitelist → ValueError (safe failure)
- Deeply nested expressions could hit Python's recursion limit (unlikely with LLM-generated math)

---

## Decision: OpenAI SDK (GPT-4o-mini) as LLM Provider

### Context
The project needs an LLM for the orchestrator and later for the evaluation judge. Needed to choose between Anthropic and OpenAI SDKs.

### Options considered
1. **OpenAI SDK** — cheapest per-token pricing (GPT-4o-mini), mature function-calling, broad documentation
2. **Anthropic SDK** — strong models, but API credits are separate from chat credits

### Decision
OpenAI SDK. GPT-4o-mini for agent calls, GPT-4o available for more capable tasks.

### Why
- GPT-4o-mini is ~5x cheaper per token than Claude Haiku (~$0.15/M input vs ~$0.80/M)
- OpenAI's function-calling API is mature and well-documented
- Estimated total project cost: $3–6 across all phases
- The orchestrator logic is provider-agnostic; only the API call layer is OpenAI-specific

### Tradeoffs
- OpenAI models may behave slightly differently on tool-calling edge cases compared to Claude
- Locked into OpenAI's pricing and availability
- Switching providers later requires changing the API layer (but not orchestrator state machine or tool logic)

---

## Decision: asyncpg Without ORM

### Context
Needed a database access layer for PostgreSQL.

### Options considered
1. **SQLAlchemy (async)** — full ORM, query builder, migration support
2. **asyncpg** — raw async Postgres driver, no abstraction
3. **Tortoise ORM** — async ORM for Python

### Decision
Raw asyncpg with plain SQL queries.

### Why
- Minimal abstraction — every query is visible and explainable
- No ORM concepts to explain that aren't relevant to the project
- asyncpg is the fastest Python Postgres driver
- The schema is small (6 tables at most) — an ORM's value is low

### Tradeoffs
- No migration tooling (schema changes require manual SQL)
- No query builder (must write SQL strings)
- No model mapping (must convert rows to dicts/models manually)

---

## Decision: Base Tool Abstraction with Pydantic Input Validation

### Context
had only one tool (calculator) with an ad-hoc interface. adds two more tools and needs a consistent contract.

### Options considered
1. **No abstraction** — each tool is a standalone class with its own interface
2. **ABC with JSON Schema validation** — `jsonschema` library validates input dicts
3. **ABC with Pydantic input models** — each tool defines a Pydantic model for its input

### Decision
ABC with Pydantic input models. Each tool implements `input_model()` returning a Pydantic class. The base class `__call__` validates input through the model before calling `execute()`.

### Why
- Pydantic is already a dependency (used for AgentAnswer)
- Input validation happens automatically before execute() — tools can't receive invalid input
- `model_json_schema()` generates the OpenAI function schema directly — no manual JSON Schema maintenance
- Type safety: execute() receives a validated Pydantic model, not a raw dict

### Tradeoffs
- Tools must define a Pydantic model even for simple inputs (minor boilerplate)
- Tight coupling between validation and Pydantic (acceptable since it's already in the stack)

---

## Decision: Deterministic Stub for Web Search Tool

### Context
The agent needs a web search tool to exercise multi-tool reasoning, but real search APIs return different results over time.

### Options considered
1. **Real API** (Google, Bing, SerpAPI) — live results, realistic behavior
2. **Deterministic stub** — canned results for known queries, empty for unknown

### Decision
Deterministic stub with canned results.

### Why
- Reproducibility: deterministic outputs make testing and debugging straightforward
- Cost: real search APIs cost money per query; stubs are free
- Test stability: tests don't break when search results change
- The tool's purpose is to demonstrate multi-tool orchestration, not to be a production search engine

### Tradeoffs
- No real search results — the agent can only "find" things in the canned dataset
- Doesn't exercise error handling for real API failures (but the retry wrapper handles that generically)

---

## Decision: Exponential Backoff with Error Classification

### Context
LLM API calls fail transiently — timeouts, rate limits, server errors. Need a retry strategy.

### Options considered
1. **No retry** — fail immediately on any error
2. **Fixed delay retry** — wait N seconds, retry up to K times
3. **Exponential backoff** — delay doubles each attempt (1s, 2s, 4s)
4. **Library-based** (tenacity) — decorator-based retry with backoff

### Decision
Custom exponential backoff with error classification. Retry only retryable errors (timeout, rate limit, connection, HTTP 5xx). Raise immediately on non-retryable errors (bad request, auth failure, validation).

### Why
- Exponential backoff reduces thundering herd on rate-limited services
- Error classification prevents wasting money retrying errors that will never succeed
- Custom implementation keeps the retry logic visible and easy to debug
- Max 3 attempts balances reliability vs. latency

### Tradeoffs
- No jitter (could add if needed, but overkill for single-client agent)
- No per-error-type backoff tuning (rate limit errors could respect Retry-After header)
- Custom code instead of tenacity — more to maintain, but more transparent

---

## Decision: OpenTelemetry for Tracing Over Custom Logging

### Context
adds per-step tracing to the orchestrator. Need to choose how to create and manage spans for each step.

### Options considered
1. **Custom logging** — structured log lines with step data (JSON logs)
2. **OpenTelemetry SDK** — industry-standard tracing API with span context
3. **Datadog/New Relic SDK** — vendor-specific APM

### Decision
OpenTelemetry SDK (opentelemetry-api + opentelemetry-sdk).

### Why
- Industry standard — same API regardless of backend (Jaeger, Zipkin, OTLP)
- Span context propagation is built in — parent/child relationships come free
- Attributes on spans give us structured metadata (tokens, cost, latency) without parsing logs
- Adding an exporter later (Jaeger, console) is a one-line config change

### Tradeoffs
- Two new dependencies (opentelemetry-api, opentelemetry-sdk)
- We persist spans to our own Postgres table rather than shipping to an OTel collector — means we get queryable traces via our API but don't get the Jaeger/Zipkin UI for free
- OTel SDK has a learning curve (tracers, spans, attributes, context propagation)

---

## Decision: Postgres Span Persistence Over OTel Collector

### Context
OTel spans need to go somewhere. Options are an external collector/backend or our own database.

### Options considered
1. **OTel Collector → Jaeger** — standard pipeline, rich visualization UI
2. **Persist to Postgres** — spans table alongside runs, queryable via our API
3. **Both** — dual export

### Decision
Persist to Postgres only. No external collector.

### Why
- The project's value proposition is that traces are queryable via the API — GET /runs/{id} returns spans, GET /runs/{id}/cost returns cost breakdown
- Adding Jaeger would mean another Docker service, another dependency
- The spans table gives us full SQL queryability — aggregate cost by tool, find slowest steps, etc.
- If we wanted Jaeger later, adding an exporter is additive, not a migration

### Tradeoffs
- No Jaeger/Zipkin visualization UI — traces are JSON via the API, not a waterfall diagram
- Must write our own persistence code instead of using OTel's built-in exporters
- Span data format is ours, not the OTLP standard — less portable

---

## Decision: Static Pricing Table Over API-Based Pricing

### Context
Need to compute per-step cost from token counts. Pricing data has to come from somewhere.

### Options considered
1. **Hardcoded table** — dict mapping model names to per-token prices
2. **API lookup** — fetch current pricing from OpenAI at runtime
3. **Config file** — pricing in YAML/JSON, editable without code changes

### Decision
Hardcoded static dict in `src/pricing.py`.

### Why
- OpenAI has no pricing API — there's no endpoint to query current prices
- Pricing changes rarely (quarterly at most) — a dict update is a one-line code change
- No external dependency, no failure mode, no caching needed
- Uses Decimal for exact arithmetic — no floating-point rounding on financial calculations

### Tradeoffs
- Must manually update when OpenAI changes prices
- Only includes models we actually use (gpt-4o-mini, gpt-4o)
- Unknown models return $0 cost rather than erroring

---

## Decision: Structured Output Repair via LLM Feedback

### Context
When the LLM's final answer fails Pydantic validation (e.g., confidence: 5.0), failed the entire run. needs to recover.

### Options considered
1. **Fail the run** — current behavior, simplest
2. **Retry silently** — call LLM again with the same prompt
3. **Repair with error feedback** — send the Pydantic error message back to the LLM and ask it to fix the output

### Decision
Repair with error feedback. One retry attempt. If the repair also fails validation, fail the run.

### Why
- The Pydantic error message is specific: "confidence must be ≤ 1.0". Feeding this back gives the LLM the exact information it needs to fix the output.
- Silent retry without feedback is unlikely to produce a different result
- One retry caps the additional cost at one extra LLM call

### Tradeoffs
- One extra LLM call on validation failure (cost: ~$0.001 for GPT-4o-mini)
- If the LLM consistently produces invalid output, the repair won't help — but that's a prompt engineering problem, not an infrastructure one

---

## Decision: Content-Hash Cache in Redis

### Context
The agent makes LLM API calls that cost money. Identical questions produce identical orchestrator steps. If the same step (same type + same input) runs again, we should return the cached result instead of paying for another API call.

### Options considered
1. **No cache** — every run calls the LLM
2. **In-memory dict** — fast, but lost on restart, no sharing across instances
3. **Redis with content-hash keys** — SHA-256 of (step_type + normalized_input) as key, JSON-serialized response as value, 1-hour TTL

### Decision
Redis with content-hash keys.

### Why
- SHA-256 makes the key deterministic and collision-resistant
- Step_type in the key prevents cross-step collisions (plan vs observe with the same data)
- JSON.dumps with sort_keys=True ensures key-order-independent normalization
- Redis is already in the stack (docker-compose.yml)
- 1-hour TTL balances cost savings vs. freshness
- Graceful degradation: if Redis is down, cache_get returns None and the agent runs normally

### Tradeoffs
- Extra latency per step (~1ms Redis roundtrip) even on misses — negligible vs. LLM call latency
- Stale results possible within the TTL window — acceptable for this use case
- Cache key includes the full messages list for observe/repair steps — large keys hash fine but large values consume Redis memory
- Using MagicMock to reconstruct cached responses — works but isn't typed

### Failure modes
- Redis down: graceful degradation, no cache, agent runs normally
- Corrupted cache entry: JSON decode failure caught, returns None, LLM called
- TTL too short: more cache misses, more LLM calls (tunable)
- TTL too long: stale answers served (1 hour is a safe default)

---

## Decision: Cache at Step Level, Not Run Level

### Context
Could cache entire runs (same question → same answer) or individual steps (same step input → same step output).

### Options considered
1. **Run-level cache** — cache the final answer for a complete question
2. **Step-level cache** — cache each LLM call independently

### Decision
Step-level cache.

### Why
- A multi-step run might share some steps with a previous run but diverge later — step-level caching captures partial reuse
- Step-level cache is composable: same plan step can be reused even if later steps differ
- Aligns with the per-step cost accounting — cache_hit is a span-level attribute

### Tradeoffs
- More cache entries than run-level (multiple keys per run)
- Slightly more complex integration (each handler checks cache independently)
- Run-level would be simpler but misses partial reuse

---

## Decision: Graceful Degradation on Cache Failure

### Context
Redis might be down or unreachable. The cache should not become a single point of failure.

### Options considered
1. **Fail the run** — raise if Redis is unavailable
2. **Graceful degradation** — catch exceptions, log, proceed without cache
3. **Circuit breaker** — stop trying cache after N failures

### Decision
Graceful degradation with logging.

### Why
- The cache is a performance optimization, not a correctness requirement
- The agent must work without caching (tests run without Redis)
- Logging the failure provides visibility without blocking the run
- A circuit breaker adds complexity for minimal benefit at this scale

---

## Decision: Broad Exception Handling at API Boundary

### Context
Found during a self-audit: `POST /run` only caught `OrchestratorError`, but `_call_llm` can raise raw OpenAI SDK exceptions (`AuthenticationError`, `APITimeoutError` after retry exhaustion). These propagated as HTTP 500s and left run records permanently stuck at `status='running'`.

### Options considered
1. **Wrap `_call_llm`'s final raise** in `OrchestratorError` — keep the catch clause narrow
2. **Broaden the except clause** to `Exception` at the API boundary — catch everything

### Decision
Broaden to `except Exception` at the API boundary.

### Why
- The API boundary is the last line of defense — no exception should leave a run stuck
- Wrapping in `_call_llm` would hide the original exception type in logs
- `logger.exception()` preserves the full traceback for debugging
- The run always transitions to `status='failed'` with an error message

### Tradeoffs
- Catches everything, including truly unexpected errors (e.g., programming bugs) — but a stuck run with no error is worse than a failed run with an error message
- Could mask bugs that should crash the process — mitigated by `logger.exception()` which logs the full traceback

---

## Decision: Consolidate Cache Logic into _cached_llm_call Helper

### Context
After implementing cache integration, three handlers (`_plan`, `_observe`, `_repair_output`) each had a near-identical 8-line block: compute cache key → check → hit/miss → build mock or call LLM → store. Found during self-audit as tech debt.

### Options considered
1. **Keep inline** — three copies, each handler is self-contained
2. **Extract to `_cached_llm_call` helper** — one function returns `(response, tokens_in, tokens_out, hit)`
3. **Decorator on `_call_llm`** — transparent caching

### Decision
Extract to `_cached_llm_call` helper method.

### Why
- Eliminates three copies of the same logic — one place to fix bugs
- Returns a tuple that the caller destructures — explicit, no hidden behavior
- A decorator would hide the cache key computation, making it harder to explain and debug

### Tradeoffs
- Callers must pass both `cache_input` (for key) and `messages` (for LLM call) — slight signature complexity
- The helper doesn't record spans or set OTel attributes — callers still handle that, which keeps span logic visible

---

## Decision: Zero Tokens on Cache-Hit Spans

### Context
Cache-hit spans originally stored the historical token counts from the run that first populated the cache. This inflated `CostBreakdown.total_tokens_in/out` even though zero API calls were made.

### Options considered
1. **Keep historical tokens** — span shows what the response "cost" originally, useful for debugging
2. **Zero out tokens** — span reflects actual API usage (0 calls = 0 tokens)
3. **Split into actual vs. represented** — two fields on CostBreakdown

### Decision
Zero out tokens on cache hits.

### Why
- `total_tokens_in/out` should reconcile with real OpenAI billing — historical tokens don't
- `cost_usd=0` already correctly reflects no API call; tokens should match
- The cached entry still stores the original token counts internally for response reconstruction
- Adding a second set of fields would complicate the API for a niche use case
