import json
from uuid import UUID

import asyncpg

from src.config import settings
from src.models import AgentAnswer, RunStatus

_pool: asyncpg.Pool | None = None


async def init_db() -> None:
    global _pool
    _pool = await asyncpg.create_pool(settings.database_url)


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


async def create_run(question: str) -> dict:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO runs (input_question, status) VALUES ($1, $2) "
            "RETURNING id, created_at",
            question,
            RunStatus.RUNNING.value,
        )
        return dict(row)


async def complete_run(run_id: UUID, answer: AgentAnswer) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE runs SET status = $1, final_answer = $2 WHERE id = $3",
            RunStatus.COMPLETED.value,
            json.dumps(answer.model_dump()),
            run_id,
        )


async def fail_run(run_id: UUID, error: str) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE runs SET status = $1 WHERE id = $2",
            RunStatus.FAILED.value,
            run_id,
        )


async def get_run(run_id: UUID) -> dict | None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        return dict(row) if row else None
