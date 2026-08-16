from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class Citation(BaseModel):
    source: str
    text: str


class AgentAnswer(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SpanRecord(BaseModel):
    id: UUID
    run_id: UUID
    step_index: int
    step_type: str
    tool_name: str | None = None
    input_json: dict | None = None
    output_json: dict | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    cache_hit: bool = False
    latency_ms: float
    started_at: datetime
    ended_at: datetime


class RunRequest(BaseModel):
    question: str


class RunResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    question: str
    answer: AgentAnswer | None = None
    error: str | None = None
    created_at: datetime
    total_cost_usd: Decimal = Decimal("0")
    spans: list[SpanRecord] = Field(default_factory=list)


class CostBreakdown(BaseModel):
    run_id: UUID
    total_cost_usd: Decimal
    total_tokens_in: int
    total_tokens_out: int
    spans: list[SpanRecord]
