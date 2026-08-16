import json
import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException

from src import db
from src.models import AgentAnswer, RunRequest, RunResponse, RunStatus
from src.orchestrator import Orchestrator, OrchestratorError
from src.tools import build_tool_map

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield
    await db.close_db()


app = FastAPI(title="Agent Platform", version="0.2.0", lifespan=lifespan)


def _build_orchestrator() -> Orchestrator:
    return Orchestrator(tools=build_tool_map())


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
        answer = await orchestrator.run(request.question)
        await db.complete_run(run_id, answer)
        return RunResponse(
            run_id=run_id,
            status=RunStatus.COMPLETED,
            question=request.question,
            answer=answer,
            created_at=created_at,
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

    return RunResponse(
        run_id=row["id"],
        status=RunStatus(row["status"]),
        question=row["input_question"],
        answer=answer,
        created_at=row["created_at"],
    )
