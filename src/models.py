from datetime import datetime
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


class RunRequest(BaseModel):
    question: str


class RunResponse(BaseModel):
    run_id: UUID
    status: RunStatus
    question: str
    answer: AgentAnswer | None = None
    error: str | None = None
    created_at: datetime
