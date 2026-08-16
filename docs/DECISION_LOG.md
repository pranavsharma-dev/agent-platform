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
- Maps directly to OpenTelemetry spans (Phase 3)
- Each state handler is a focused function
- State transitions can be asserted in tests
- Easy to explain in an interview

### Tradeoffs
- More code than a simple while loop
- Must manually manage state transitions (risk of forgetting an edge case)
- Slightly more complex than necessary for a simple calculator-only agent

### Failure modes
- Infinite loop if a state transition cycles without advancing (mitigated by max_steps)
- State that doesn't match any handler (mitigated by exhaustive match and default error)

### Alternative implementation
A LangChain `AgentExecutor` hides the loop entirely. You define tools and a prompt, and the framework runs the loop. This is faster to build but you lose visibility into state transitions, can't instrument individual steps, and can't easily explain the control flow.

### Interview question
"Why did you build your own orchestration loop instead of using LangChain?"

### Interview answer
"I chose an explicit state machine because I wanted the agent's control flow to be observable. Instead of letting a framework hide the loop, I made PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, and FINALIZE explicit states. Each transition gets logged, and in Phase 3 each one becomes an OpenTelemetry span. I can write tests that assert the exact sequence of state transitions for a given input. With LangChain, the loop is a black box — I'd lose the observability that's the whole point of this project."

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
- Easy to explain the security reasoning

### Tradeoffs
- More code than `eval()`
- Limited to basic arithmetic (no functions like sqrt, sin)
- Need to handle each operator explicitly

### Failure modes
- Missing operator in the whitelist → ValueError (safe failure)
- Deeply nested expressions could hit Python's recursion limit (unlikely with LLM-generated math)

### Interview question
"Why didn't you just use eval() for the calculator?"

### Interview answer
"The LLM controls the expression string, so eval() is a code injection risk. If the model hallucinates or is prompt-injected, eval() would execute arbitrary Python. Instead I parse the expression into an AST and only allow arithmetic nodes — constants, binary operators, unary operators. Anything else raises a ValueError. It's a few more lines of code, but it's secure by construction."

---

## Decision: OpenAI SDK (GPT-4o-mini) as LLM Provider

### Context
The project needs an LLM for the orchestrator and later for the evaluation judge. Needed to choose between Anthropic and OpenAI SDKs.

### Options considered
1. **OpenAI SDK** — cheapest per-token pricing (GPT-4o-mini), mature function-calling, broad documentation
2. **Anthropic SDK** — strong models, but API credits are separate from chat credits

### Decision
OpenAI SDK. GPT-4o-mini for agent calls, GPT-4o for the judge (Phase 5).

### Why
- GPT-4o-mini is ~5x cheaper per token than Claude Haiku (~$0.15/M input vs ~$0.80/M)
- OpenAI's function-calling API is mature and well-documented
- Estimated total project cost: $3–6 across all phases
- The orchestrator logic is provider-agnostic; only the API call layer is OpenAI-specific

### Tradeoffs
- OpenAI models may behave slightly differently on tool-calling edge cases compared to Claude
- Locked into OpenAI's pricing and availability
- Switching providers later requires changing the API layer (but not orchestrator state machine or tool logic)

### Interview question
"Why did you choose OpenAI over Anthropic?"

### Interview answer
"Cost was the deciding factor. GPT-4o-mini is roughly five times cheaper per token than Claude Haiku, and for a project that runs hundreds of evaluation cases, that adds up. The orchestrator logic is provider-agnostic — the state machine, tool registry, and retry policy don't know which LLM is behind the API call. Only the _call_llm method and response parsing are OpenAI-specific, so switching providers would be a contained change."

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

### Interview question
"Why raw SQL instead of SQLAlchemy?"

### Interview answer
"The schema is deliberately small — six tables at most. An ORM adds abstraction I'd need to explain but doesn't solve a real problem at this scale. With asyncpg, every query is visible SQL, the connection pooling is built in, and it's the fastest Python Postgres driver. If the project grew to 30+ tables, I'd add SQLAlchemy for the migration tooling alone."

---

## Decision: Base Tool Abstraction with Pydantic Input Validation

### Context
Phase 1 had only one tool (calculator) with an ad-hoc interface. Phase 2 adds two more tools and needs a consistent contract.

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

### Interview question
"Why Pydantic for tool input validation instead of JSON Schema?"

### Interview answer
"Pydantic was already in the project for structured output validation, so no new dependency. It gives me three things at once: input validation before execute(), automatic JSON Schema generation for the OpenAI function-calling format, and type-safe execute() methods that receive validated models instead of raw dicts. The base class __call__ method validates input, so tool implementations can't accidentally receive bad data."

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
- Evaluation reliability: the eval harness (Phase 5) needs reproducible results to detect regressions
- Cost: real search APIs cost money per query; stubs are free
- Test stability: tests don't break when search results change
- The tool's purpose is to demonstrate multi-tool orchestration, not to be a production search engine

### Tradeoffs
- No real search results — the agent can only "find" things in the canned dataset
- Doesn't exercise error handling for real API failures (but the retry wrapper handles that generically)

### Interview question
"Why not use a real search API?"

### Interview answer
"Eval reliability. If search results change between eval runs, I can't tell whether a quality regression came from my code or from different search results. The stub gives me reproducible inputs so the eval harness isolates my agent's behavior. In production I'd swap in a real API — the tool interface is the same."

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
- Custom implementation keeps the retry logic visible and interview-defensible — no library to explain
- Max 3 attempts balances reliability vs. latency

### Tradeoffs
- No jitter (could add if needed, but overkill for single-client agent)
- No per-error-type backoff tuning (rate limit errors could respect Retry-After header)
- Custom code instead of tenacity — more to maintain, but more transparent

### Interview question
"Why not use tenacity for retries?"

### Interview answer
"I wanted the retry logic to be visible, not hidden in a decorator. The error classification — is this retryable or not — is specific to the OpenAI SDK's exception hierarchy, and I wanted to be able to explain every branch. The whole retry wrapper is about 15 lines. Tenacity would save those 15 lines but add a dependency I'd need to explain."

---

## Decision: OpenTelemetry for Tracing Over Custom Logging

### Context
Phase 3 adds per-step tracing to the orchestrator. Need to choose how to create and manage spans for each step.

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
- Interview-friendly: OTel is the answer hiring managers expect for "how do you observe your services"

### Tradeoffs
- Two new dependencies (opentelemetry-api, opentelemetry-sdk)
- We persist spans to our own Postgres table rather than shipping to an OTel collector — means we get queryable traces via our API but don't get the Jaeger/Zipkin UI for free
- OTel SDK has a learning curve (tracers, spans, attributes, context propagation)

### Interview question
"Why OpenTelemetry instead of just structured logging?"

### Interview answer
"Structured logs give you searchable events, but not the parent-child relationships that make a trace. OpenTelemetry gives me spans with context propagation — the root span is the agent run, and each step (plan, tool_call, observe) is a child span. I can see the full tree of what happened, with timing, token counts, and cost as span attributes. I persist the spans to Postgres so they're queryable via my own API, but I could add a Jaeger exporter in one line if I wanted the UI."

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
- Adding Jaeger would mean another Docker service, another dependency, another thing to explain in an interview
- The spans table gives us full SQL queryability — aggregate cost by tool, find slowest steps, etc.
- If we wanted Jaeger later, adding an exporter is additive, not a migration

### Tradeoffs
- No Jaeger/Zipkin visualization UI — traces are JSON via the API, not a waterfall diagram
- Must write our own persistence code instead of using OTel's built-in exporters
- Span data format is ours, not the OTLP standard — less portable

### Interview question
"Why not use Jaeger for visualization?"

### Interview answer
"The traces need to be accessible via the API — that's the 'inspectable and attributable' claim. Persisting to Postgres means GET /runs/{id} returns the full trace with token counts and costs. Adding Jaeger would give me a nice waterfall UI but add another service to manage. The span data is in Postgres alongside the run record, so I can join them, aggregate costs, and build any view I need. If I wanted Jaeger, I'd add an OTLP exporter — it's additive."

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

### Interview question
"What happens when OpenAI changes their pricing?"

### Interview answer
"I update two lines in the pricing dict and redeploy. OpenAI doesn't have a pricing API, so there's no way to fetch current prices at runtime. The pricing table uses Python Decimal for exact arithmetic — I don't want floating-point rounding errors accumulating across hundreds of eval runs."

---

## Decision: Structured Output Repair via LLM Feedback

### Context
When the LLM's final answer fails Pydantic validation (e.g., confidence: 5.0), Phase 1 failed the entire run. Phase 2 needs to recover.

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

### Interview question
"Walk me through what happens when the LLM returns confidence: 5.0."

### Interview answer
"Pydantic catches it — confidence must be between 0.0 and 1.0. Instead of failing the run, I append a message to the conversation: 'Your response couldn't be parsed. Error: confidence must be ≤ 1.0. Please respond with only a valid JSON object.' Then I call the LLM again. It now has the original conversation plus the specific validation error, so it can fix the exact issue. If the second attempt also fails validation, then the run fails. One retry, specific feedback, capped cost."

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

### Alternative implementation
An in-memory LRU cache (functools.lru_cache) would be simpler but wouldn't survive process restarts, wouldn't be shared across instances, and wouldn't support TTL.

### Interview question
"How does the cache work?"

### Interview answer
"Before each LLM call, I compute a SHA-256 hash of the step type plus the normalized input — JSON.dumps with sorted keys. I check Redis for that key. On a hit, I reconstruct the response from the cached data — the content, any tool calls, finish reason, and token counts — and skip the API call entirely. Cost for that step is zero. On a miss, I call the LLM, serialize the response, and store it with a 1-hour TTL. If Redis is down, the agent runs normally without caching."

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

### Interview question
"Why not cache the whole run?"

### Interview answer
"Step-level caching captures partial reuse. If the same question triggers the same plan and calculator call but the observe step diverges, I still save the plan call's cost. Run-level caching is all-or-nothing — a slightly different conversation path means a full cache miss."

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

### Interview question
"What happens if Redis goes down?"

### Interview answer
"The agent keeps running. cache_get returns None on any exception — it's treated as a cache miss. cache_set fails silently with a warning log. The cost is higher because every step calls the LLM, but no runs fail. This was a deliberate design choice — the cache is a cost optimization, not a correctness dependency."

---

## Decision: Broad Exception Handling at API Boundary

### Context
Found during a Phase 4 self-audit: `POST /run` only caught `OrchestratorError`, but `_call_llm` can raise raw OpenAI SDK exceptions (`AuthenticationError`, `APITimeoutError` after retry exhaustion). These propagated as HTTP 500s and left run records permanently stuck at `status='running'`.

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

### Interview question
"What happens if the OpenAI API key is wrong?"

### Interview answer
"The orchestrator's retry logic classifies `AuthenticationError` as non-retryable and raises immediately. The API handler catches it with a broad `except Exception`, logs the full traceback, marks the run as failed with the error message, and returns a clean JSON response. I found this gap during a self-audit — originally the handler only caught my own `OrchestratorError` type, which meant raw SDK exceptions left runs stuck at 'running' forever. I confirmed it by running the stack with a bad API key and checking the database."

---

## Decision: Consolidate Cache Logic into _cached_llm_call Helper

### Context
After implementing Phase 4 cache integration, three handlers (`_plan`, `_observe`, `_repair_output`) each had a near-identical 8-line block: compute cache key → check → hit/miss → build mock or call LLM → store. Found during Phase 4 self-audit as tech debt.

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

### Interview question
"Why not use a decorator for caching?"

### Interview answer
"The cache key depends on the step type and a normalized input dict that varies per handler — `_plan` uses the question, `_observe` uses the full messages list. A decorator couldn't determine the right key without the handler telling it what to hash. The helper takes the step type and cache input explicitly, which keeps the key computation visible and testable."

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

### Interview question
"Does your token count reconcile with your OpenAI billing dashboard?"

### Interview answer
"Yes, now it does. Cache-hit spans report zero tokens because no API call was made. The cost is zero too. Originally I stored the historical token counts from the first run, which inflated the totals — I caught that in a self-audit and fixed it."
