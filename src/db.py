import json
from datetime import datetime
from decimal import Decimal
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
            "UPDATE runs SET status = $1, error_message = $2 WHERE id = $3",
            RunStatus.FAILED.value,
            error,
            run_id,
        )


async def update_run_cost(run_id: UUID, total_cost: Decimal) -> None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE runs SET total_cost_usd = $1 WHERE id = $2",
            total_cost,
            run_id,
        )


async def get_run(run_id: UUID) -> dict | None:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM runs WHERE id = $1", run_id)
        return dict(row) if row else None


async def insert_span(
    run_id: UUID,
    step_index: int,
    step_type: str,
    tool_name: str | None,
    input_json: dict | None,
    output_json: dict | None,
    tokens_in: int,
    tokens_out: int,
    cost_usd: Decimal,
    cache_hit: bool,
    latency_ms: float,
    started_at: datetime,
    ended_at: datetime,
) -> UUID:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO spans "
            "(run_id, step_index, step_type, tool_name, input_json, output_json, "
            "tokens_in, tokens_out, cost_usd, cache_hit, latency_ms, started_at, ended_at) "
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id",
            run_id,
            step_index,
            step_type,
            tool_name,
            json.dumps(input_json) if input_json is not None else None,
            json.dumps(output_json) if output_json is not None else None,
            tokens_in,
            tokens_out,
            cost_usd,
            cache_hit,
            latency_ms,
            started_at,
            ended_at,
        )
        return row["id"]


async def get_spans(run_id: UUID) -> list[dict]:
    assert _pool is not None
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM spans WHERE run_id = $1 ORDER BY step_index",
            run_id,
        )
        return [dict(r) for r in rows]
