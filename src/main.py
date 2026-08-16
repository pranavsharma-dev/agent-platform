import json
import logging
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI, HTTPException

from src import db
from src.models import (
    AgentAnswer,
    CostBreakdown,
    RunRequest,
    RunResponse,
    RunStatus,
    SpanRecord,
)
from src.orchestrator import Orchestrator, OrchestratorError
from src.tools import build_tool_map

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="Agent Platform", version="0.3.0", lifespan=lifespan)


def _build_orchestrator() -> Orchestrator:
    return Orchestrator(tools=build_tool_map())


def _parse_spans(raw_rows: list[dict]) -> list[SpanRecord]:
    spans = []
    for row in raw_rows:
        input_json = row.get("input_json")
        output_json = row.get("output_json")
        if isinstance(input_json, str):
            input_json = json.loads(input_json)
        if isinstance(output_json, str):
            output_json = json.loads(output_json)
        spans.append(SpanRecord(
            id=row["id"],
            run_id=row["run_id"],
            step_index=row["step_index"],
            step_type=row["step_type"],
            tool_name=row.get("tool_name"),
            input_json=input_json,
            output_json=output_json,
            tokens_in=row.get("tokens_in", 0),
            tokens_out=row.get("tokens_out", 0),
            cost_usd=row.get("cost_usd", Decimal("0")),
            cache_hit=row.get("cache_hit", False),
            latency_ms=row["latency_ms"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
        ))
    return spans


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/run", response_model=RunResponse)
async def run_agent(request: RunRequest):
    run_record = await db.create_run(request.question)
    run_id = run_record["id"]
    created_at = run_record["created_at"]

    orchestrator = _build_orchestrator()
    try:
        answer = await orchestrator.run(request.question, run_id=run_id)
        await db.complete_run(run_id, answer)

        span_rows = await db.get_spans(run_id)
        spans = _parse_spans(span_rows)
        run_row = await db.get_run(run_id)
        total_cost = run_row["total_cost_usd"] if run_row else Decimal("0")

        return RunResponse(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            question=request.question,
            answer=answer,
            created_at=created_at,
            total_cost_usd=total_cost,
            spans=spans,
        )
    except OrchestratorError as e:
        await db.fail_run(run_id, str(e))
        return RunResponse(
            run_id=run_id,
            status=RunStatus.FAILED,
            question=request.question,
            error=str(e),
            created_at=created_at,
        )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: UUID):
    row = await db.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    answer = None
    if row["final_answer"] is not None:
        raw = row["final_answer"]
        answer_data = json.loads(raw) if isinstance(raw, str) else raw
        answer = AgentAnswer(**answer_data)

    span_rows = await db.get_spans(run_id)
    spans = _parse_spans(span_rows)

    return RunResponse(
        run_id=row["id"],
        status=RunStatus(row["status"]),
        question=row["input_question"],
        answer=answer,
        created_at=row["created_at"],
        total_cost_usd=row.get("total_cost_usd", Decimal("0")),
        spans=spans,
    )


@app.get("/runs/{run_id}/cost", response_model=CostBreakdown)
async def get_run_cost(run_id: UUID):
    row = await db.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Run not found")

    span_rows = await db.get_spans(run_id)
    spans = _parse_spans(span_rows)

    total_tokens_in = sum(s.tokens_in for s in spans)
    total_tokens_out = sum(s.tokens_out for s in spans)

    return CostBreakdown(
        run_id=run_id,
        total_cost_usd=row.get("total_cost_usd", Decimal("0")),
        total_tokens_in=total_tokens_in,
        total_tokens_out=total_tokens_out,
        spans=spans,
    )
