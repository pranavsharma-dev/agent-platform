# Glossary

## Orchestration
The process of coordinating multiple steps — LLM calls, tool executions, validation — into a coherent workflow. The orchestrator manages what happens next based on the current state.

## State Machine
A model of computation with a finite set of named states and defined transitions between them. Our orchestrator has 7 states: PLAN, SELECT_TOOL, CALL_TOOL, OBSERVE, FINALIZE, ERROR, COMPLETE. At any moment, the system is in exactly one state.

## Tool Calling
The pattern where an LLM requests execution of an external function. The LLM outputs a tool name and structured arguments; the orchestrator validates and executes the tool; the result is sent back to the LLM.

## Structured Output
LLM output that conforms to a predefined schema (JSON with specific fields and types) rather than free-form text. We use Pydantic models to define and validate the expected structure.

## Pydantic
A Python library for data validation using type annotations. We define models like `AgentAnswer(answer: str, citations: list[Citation], confidence: float)` and Pydantic validates that LLM output matches the schema.

## Retryable Error
*(Phase 2)* An error that may succeed if tried again — timeouts, rate limits, transient network failures.

## Non-Retryable Error
*(Phase 2)* An error that will fail every time — invalid input schema, malformed request, authentication failure. Retrying wastes money.

## Exponential Backoff
*(Phase 2)* A retry strategy where wait time increases exponentially: 1s, 2s, 4s, 8s... Prevents overwhelming a service that's already struggling.

## OpenTelemetry
*(Phase 3)* An open standard for distributed tracing. Defines traces (end-to-end request flows) and spans (individual operations within a trace).

## Trace
*(Phase 3)* A complete record of everything that happened during one agent run — every LLM call, tool execution, and state transition, with timing and metadata.

## Span
*(Phase 3)* A single timed operation within a trace. Our orchestrator creates spans for: plan, tool call, LLM call. Each span carries attributes like tool name, tokens, latency, cache status.

## Token Accounting
*(Phase 3)* Counting input and output tokens for every LLM call and computing dollar cost using a pricing table.

## Cost Ledger
*(Phase 3)* A database table that records token usage and cost per step, enabling per-run cost attribution.

## Content Hash
*(Phase 4)* A SHA-256 hash of the step type plus normalized input. Used as a cache key — identical inputs produce identical hashes.

## Cache Hit
*(Phase 4)* When the content hash exists in Redis, the cached output is returned without making the actual LLM/tool call. Cost for that step is zero.

## Deterministic Grader
*(Phase 5)* An evaluation function that produces the same score for the same input every time — exact match, citation validation, schema check. No LLM involved.

## LLM Judge
*(Phase 5)* A separate LLM call that scores an agent's answer against an expected answer using a rubric. Handles nuanced quality assessment that deterministic graders can't.

## Calibration
*(Phase 6)* Comparing LLM judge labels against human labels to validate that the judge is trustworthy. Measured by agreement rate and Cohen's kappa.

## Cohen's Kappa
*(Phase 6)* A statistic that measures agreement between two raters (human and judge) while accounting for agreement by chance. κ=1 is perfect agreement, κ=0 is chance-level.

## Regression Evaluation
*(Phase 7)* Running the eval suite and comparing results to a stored baseline. A quality drop or cost increase beyond thresholds indicates a regression.

## Baseline
*(Phase 7)* A stored record of the evaluation scores and costs from a known-good version. New eval runs are compared against it.

## CI Gate
*(Phase 7)* A step in the CI pipeline that fails the build if evaluation results regress beyond defined thresholds, preventing bad changes from merging.
