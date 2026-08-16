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
