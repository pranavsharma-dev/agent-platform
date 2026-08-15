# Agent Platform

## What This Project Does

An infrastructure platform around a multi-step AI research agent that makes the agent's behavior **observable, measurable, evaluable, reproducible, and controllable**.

The agent receives a question, decides what actions to take, uses tools (search, calculator, document lookup), and produces a structured, cited answer. The platform records everything the agent did and provides infrastructure to answer:

- What did the agent do?
- Which tools did it use?
- How many LLM calls / tokens / dollars did it consume?
- Where did it fail?
- Was the answer actually good?
- Did the agent regress after a code change?
- Can repeated work be cached to save cost?

## Problem Being Solved

LLM agents are black boxes. You call the API, get an answer, and have no idea what happened in between. You can't attribute cost to individual steps, can't detect quality regressions, can't cache repeated work, and can't gate deployments on quality metrics.

This platform makes every run inspectable and attributable.

## Why It Exists

To demonstrate real engineering infrastructure skills — observability, evaluation, cost accounting, caching, CI/CD — applied to AI systems.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md).

## Tech Stack

| Layer          | Choice              |
|----------------|---------------------|
| Language       | Python 3.11+        |
| API            | FastAPI             |
| Database       | PostgreSQL          |
| Cache          | Redis               |
| Tracing        | OpenTelemetry SDK   |
| LLM            | OpenAI SDK          |
| Containers     | Docker + Compose    |
| CI             | GitHub Actions      |
| Validation     | Pydantic            |

## Current Status

**Phase 1 complete** — Skeleton with working orchestrator, calculator tool, and validated structured output.

## Resume Claims

> Built an orchestration layer for a multi-step LLM agent (tool-calling, retries, structured outputs) with per-step tracing and token/cost accounting, so every run is inspectable and attributable rather than a black box.

> Shipped a regression-eval harness — versioned eval sets, deterministic graders plus an LLM judge calibrated against human labels — wired into CI to gate merges, catching quality and cost regressions before release; a content-hash cache cuts repeat-call cost on unchanged steps.
