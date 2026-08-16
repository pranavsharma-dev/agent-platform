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
