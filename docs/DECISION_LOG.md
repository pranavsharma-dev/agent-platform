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
