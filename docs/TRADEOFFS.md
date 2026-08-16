# Tradeoffs

## Explicit State Machine vs. Framework Loop

**Problem:** How to structure the orchestrator's multi-step loop.

**Options:**
1. LangChain AgentExecutor — framework handles the loop
2. Simple while loop — flat procedural code
3. Explicit state machine — named states with typed transitions

**Chosen approach:** Explicit state machine.

**Why:** Observability is the core value proposition. Named states map to traceable steps, testable transitions, and loggable events. A framework hides this.

**Tradeoffs:**
- Gained: full visibility into control flow, testable state transitions, natural mapping to OTel spans
- Lost: speed of development, framework ecosystem (pre-built tools, memory, agents)

**When the alternative is better:** If you're building a product where time-to-market matters more than observability, and you trust the framework's loop, LangChain is faster to ship.

**Interview question:** "When would you use LangChain instead?"

**Interview answer:** "If I were building a product where shipping speed mattered more than infrastructure visibility — like a chatbot prototype — I'd use LangChain. But this project exists specifically to demonstrate observability and cost accounting at the step level. Hiding the loop inside a framework defeats the purpose. The state machine is more code, but every transition is a traceable, testable event."

---

## Safe AST Evaluator vs. eval()

**Problem:** How to evaluate mathematical expressions from LLM output.

**Options:**
1. Python eval() — simple, full language support
2. AST-based parser — whitelist-only operators
3. Third-party math library (sympy)

**Chosen approach:** AST-based parser.

**Why:** eval() accepts arbitrary Python code. LLM output is untrusted input.

**Tradeoffs:**
- Gained: security by construction — only arithmetic operations are possible
- Lost: support for mathematical functions (sqrt, sin, log)

**When the alternative is better:** If you need complex math functions, a sandboxed evaluator (sympy) or a restricted eval with `__builtins__={}` would be better. But the calculator tool's purpose is to demonstrate tool calling, not to be a full CAS.

**Interview question:** "What if the LLM needs sqrt() or logarithms?"

**Interview answer:** "I'd add those as explicit cases in the AST evaluator — map `ast.Call` nodes for specific function names to their Python math equivalents. The principle stays the same: whitelist what's allowed rather than trying to blacklist what's dangerous."

---

## asyncpg vs. SQLAlchemy ORM

**Problem:** How to interact with PostgreSQL.

**Options:**
1. SQLAlchemy (async) — ORM + query builder + migrations
2. asyncpg — raw driver, plain SQL
3. Tortoise ORM — async-native ORM

**Chosen approach:** asyncpg with plain SQL.

**Why:** Six tables total. ORM overhead isn't justified.

**Tradeoffs:**
- Gained: no abstraction layer, visible queries, fastest driver
- Lost: migration tooling, model mapping, query composition

**When the alternative is better:** 20+ tables, frequent schema changes, complex joins — SQLAlchemy's migration tooling (Alembic) and query builder earn their complexity.

**Interview question:** "What would you add if the schema grew to 30 tables?"

**Interview answer:** "Alembic for migrations, first. Then SQLAlchemy Core (not the ORM) for query composition — I want the query builder without the identity map and session tracking overhead. For a schema this small, raw SQL is clearer."

---

## Deterministic Stub vs. Real Search API

**Problem:** The agent needs web search capability, but evaluation requires reproducible results.

**Options:**
1. Real search API (SerpAPI, Google) — realistic results, but non-deterministic
2. Deterministic stub — canned results for known queries

**Chosen approach:** Deterministic stub.

**Why:** Eval reliability. The same input must produce the same output across eval runs, or you can't distinguish code regressions from data changes.

**Tradeoffs:**
- Gained: reproducible eval results, zero API cost, fast execution, test stability
- Lost: realistic search behavior, coverage of API error handling edge cases

**When the alternative is better:** In production or when testing real search quality. The tool interface is the same — swapping in a real API is a single class change.

**Interview question:** "How would you switch to a real search API?"

**Interview answer:** "Create a new class that extends BaseTool with the same name and interface, implement execute() with the real API call, and swap it in the registry. The orchestrator doesn't know or care — it calls tools through the abstract interface. For eval, I'd keep the stub to maintain reproducibility."

---

## Custom Retry vs. Tenacity Library

**Problem:** LLM API calls need retry logic for transient failures.

**Options:**
1. No retry — fail immediately
2. Tenacity library — decorator-based retry with backoff
3. Custom exponential backoff with error classification

**Chosen approach:** Custom retry with error classification.

**Why:** Transparency and defensibility. The retry wrapper is ~15 lines. The error classification is specific to OpenAI's exception hierarchy. Both are fully visible and explainable.

**Tradeoffs:**
- Gained: every retry decision is visible, no external dependency, interview-friendly
- Lost: tenacity's features (jitter, retry-after headers, composable strategies)

**When the alternative is better:** In a production system with multiple API integrations, tenacity's composable retry policies save duplication. For a single integration with simple needs, custom code is clearer.

---

## Postgres Span Storage vs. OTel Collector Pipeline

**Problem:** Where to persist trace spans.

**Options:**
1. OTel Collector → Jaeger/Zipkin — standard pipeline, built-in visualization
2. Custom Postgres table — spans alongside run records, queryable via our API

**Chosen approach:** Postgres table.

**Why:** The API is the interface. GET /runs/{id} must return spans. Postgres gives us SQL queryability (aggregate cost by tool, find slowest steps) and keeps everything in one database.

**Tradeoffs:**
- Gained: spans queryable via SQL and our API, no extra service, one database for everything
- Lost: Jaeger's waterfall visualization, OTLP-standard span format, built-in sampling

**When the alternative is better:** In a microservices system where multiple services emit spans and you need distributed trace visualization across services. For a single-service agent with an API-first interface, Postgres is simpler.

**Interview question:** "How would you add distributed trace visualization?"

**Interview answer:** "Add an OTLP exporter to the OTel SDK configuration — it's a one-line setup change. The OTel spans are already being created; I'd just add a second export destination alongside Postgres persistence. The two paths are independent."

---

## Decimal vs. Float for Cost Accounting

**Problem:** How to represent monetary values in cost calculations.

**Options:**
1. Python float — simple, fast
2. Python Decimal — exact decimal arithmetic, no rounding drift

**Chosen approach:** Decimal everywhere (pricing table, compute_cost, database column).

**Why:** Floating-point arithmetic accumulates rounding errors. Over hundreds of eval runs, small per-token costs compound. $0.000015 × 100 tokens should be exactly $0.0015, not $0.001499999999...

**Tradeoffs:**
- Gained: exact financial arithmetic, no drift across aggregation
- Lost: minor code verbosity (Decimal("0.15") vs 0.15)

**When the alternative is better:** If cost is purely informational (rough estimates, dashboards) and not used for regression detection, float is fine. Our CI gate (Phase 7) compares costs between runs — exact arithmetic matters.

**Interview question:** "Why Decimal instead of float?"

**Interview answer:** "The CI gate compares costs between eval runs — a 15% cost increase fails the build. If I use float, rounding drift across hundreds of eval cases could trigger false positives or mask real regressions. Decimal gives me exact arithmetic. The pricing table, compute_cost, and the database column all use Decimal."

---

## Step-Level Cache vs. Run-Level Cache

**Problem:** Where to place the cache boundary — cache whole runs or individual steps?

**Options:**
1. Run-level cache — same question → return cached final answer
2. Step-level cache — same step_type + same input → return cached step result

**Chosen approach:** Step-level cache.

**Why:** Partial reuse. A multi-step run might share the plan step with a previous run but diverge at the observe step. Step-level caching saves the plan call's cost even when later steps differ.

**Tradeoffs:**
- Gained: partial reuse across runs, composable cache, aligns with per-step cost model
- Lost: simplicity (multiple cache checks per run vs. one), more Redis entries

**When the alternative is better:** If questions are always identical end-to-end (no tool variance), run-level caching is simpler and equally effective.

**Interview question:** "Why not cache the whole run?"

**Interview answer:** "Step-level caching captures partial reuse. If two runs share the same plan step but diverge at observe, I still save the plan call's cost. Run-level is all-or-nothing — any difference in the conversation path means a full miss."

---

## Redis Cache vs. In-Memory Cache

**Problem:** Where to store cached LLM responses.

**Options:**
1. In-memory dict/LRU — fast, no dependency, process-local
2. Redis — shared across instances, survives restarts, TTL support

**Chosen approach:** Redis.

**Why:** Redis is already in the stack (docker-compose), supports TTL natively, and would work across multiple app instances. In-memory caches are lost on restart.

**Tradeoffs:**
- Gained: TTL support, persistence across restarts, shared across instances
- Lost: ~1ms latency per check (vs. nanosecond in-memory), requires Redis to be running

**When the alternative is better:** Single-instance, short-lived processes where restart frequency is low. functools.lru_cache would be simpler.

**Interview question:** "Why not just use an in-memory cache?"

**Interview answer:** "Redis was already in the stack, so no new infrastructure. It gives me TTL-based expiration for free, survives process restarts, and would scale to multiple instances. The ~1ms Redis roundtrip is negligible compared to a ~500ms LLM call."

---

## Broad Exception Catch vs. Typed Exception Hierarchy

**Problem:** Raw OpenAI SDK exceptions (not wrapped in `OrchestratorError`) propagated through the API handler and left run records stuck at `status='running'` forever.

**Options:**
1. Wrap every `_call_llm` raise in `OrchestratorError` — keep the API catch clause narrow
2. Broaden the API catch clause to `except Exception` — catch everything at the boundary

**Chosen approach:** Broad catch at the API boundary.

**Why:** The API boundary is the last line of defense. No exception — regardless of type — should leave a run stuck without an error message. Wrapping in `_call_llm` would hide the original exception type in logs, making debugging harder.

**Tradeoffs:**
- Gained: no run can ever get stuck, full traceback via `logger.exception()`, clean error response to client
- Lost: any exception — including programming bugs — is caught instead of crashing. Could mask logic errors.

**When the alternative is better:** In a service with a proper exception hierarchy where every external SDK call is wrapped at the integration boundary. That's the "right" design for a larger system, but requires maintaining the wrapper as the SDK evolves. At this scale, the broad catch is simpler and safer.

**Interview question:** "Isn't catching Exception too broad? Won't it mask bugs?"

**Interview answer:** "It could, but the alternative is worse. A stuck run with no error message is invisible — it looks like it's still processing. A failed run with an error message is observable. I log the full exception with traceback, so no information is lost. The tradeoff is clear: I'd rather have a run that says 'failed: TypeError on line 42' than one that sits at 'running' forever."

---

## Cache-Hit Tokens: Zero vs. Historical

**Problem:** Cache-hit spans stored the original run's token counts even though no API call was made, inflating aggregate token totals in CostBreakdown.

**Options:**
1. Report historical tokens — shows what the response "would have cost"
2. Report zero tokens — reflects actual API usage
3. Report both — add `actual_tokens` and `notional_tokens` fields

**Chosen approach:** Zero tokens on cache hits.

**Why:** `total_tokens_in/out` should reconcile with the OpenAI billing dashboard. If you made zero API calls, your aggregate token count should be zero. `cost_usd=0` was already correct; tokens should match.

**Tradeoffs:**
- Gained: token totals reconcile with real API billing, simpler mental model
- Lost: can't see how many tokens a cache hit "saved" by looking at the span alone (though you can infer it from the cached entry's stored data)

**When the alternative is better:** If you need to report "tokens saved by caching" as a metric. In that case, add a separate field rather than overloading `tokens_in`/`tokens_out` with two different meanings.
