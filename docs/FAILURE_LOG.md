# Failure Log

## Failure: Stuck runs on unhandled exceptions

**Discovered:** Post-implementation audit, 2026-08-16

**Symptom:** When `orchestrator.run()` raised a raw OpenAI SDK exception (e.g., `AuthenticationError`, `APITimeoutError` after retry exhaustion), the `POST /run` handler only caught `OrchestratorError`. The raw exception propagated as an HTTP 500, and the Postgres run row stayed permanently at `status='running'` with no error message.

**Root cause:** The except clause in `POST /run` was too narrow — it only caught `OrchestratorError`, but `_call_llm` re-raises raw SDK exceptions for non-retryable errors or after retry exhaustion.

**How it was found:** Manual code tracing during a self-audit, then reproduced live against the real Docker stack (Postgres + Redis + app). Confirmed the stuck row via `psql` query.

**Fix:** Broadened the except clause to `except Exception`, added `logger.exception()` for visibility. The run now always transitions to `status='failed'` with an error message regardless of exception type.

**Regression test:** `test_raw_exception_still_fails_run` in `tests/test_api.py` — raises `AuthenticationError` from the orchestrator and asserts the response has `status='failed'`.

**Lesson:** When the orchestrator's error type hierarchy doesn't cover all possible exceptions (because it delegates to an external SDK), the API boundary must catch broadly.

---

## Failure: Token double-counting on cache hits

**Discovered:** Post-implementation audit, 2026-08-16

**Symptom:** `GET /runs/{id}/cost` summed `tokens_in`/`tokens_out` across all spans including cache hits. Cache-hit spans stored the original run's token counts even though no API call was made, inflating aggregate token totals.

**Root cause:** On a cache hit, the code used `cr.tokens_in, cr.tokens_out` from the cached entry (the historical values from the original API call) instead of reporting 0 tokens (since no actual API call occurred).

**How it was found:** Reproduced with a scratch script — a cache-hit span reported `tokens_in=500` with 0 actual OpenAI API calls. `cost_usd` was correctly $0, but token counts were phantom values.

**Fix:** Set `tokens_in, tokens_out = 0, 0` on cache hits instead of pulling historical values from the cached entry. The cached response still has the original token counts for reconstruction purposes, but the span records reflect actual API usage.

**Impact:** `CostBreakdown.total_tokens_in/out` now accurately reflects real API token consumption. `total_cost_usd` was already correct (cache hits contributed $0).

---

## Failure: fail_run not persisting error messages

**Discovered:** Code review, 2026-08-16

**Symptom:** `db.fail_run()` accepted an error string parameter but didn't include it in the SQL UPDATE. Failed runs had `error_message=NULL` in the database.

**Root cause:** The `fail_run` function's SQL only set `status='failed'` — the `error_message` parameter was accepted but silently dropped.

**Fix:** Added `error_message` column to the runs table schema, updated the SQL to `UPDATE runs SET status=$1, error_message=$2 WHERE id=$3`.

---

## Failure: _extract_json brace-matching broke on JSON string values

**Discovered:** Code review, 2026-08-16

**Symptom:** `_extract_json` used simple brace-depth counting. JSON like `{"answer": "Use {braces} here"}` would match the inner closing brace, truncating the JSON and causing a parse error.

**Root cause:** The brace-depth counter didn't track whether it was inside a JSON string literal.

**Fix:** Added `in_string` and `escape_next` tracking to the brace-matching loop. Braces inside double-quoted strings are now ignored. Three regression tests added.
