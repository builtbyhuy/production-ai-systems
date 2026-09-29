"""Shared wire contracts. Trusted principals are resolved server-side, never from request bodies."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    return str(uuid4())


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Profile(StrEnum):
    FIXTURE = "fixture"
    LOCAL = "local"
    CONNECTED = "connected"
    DEPLOYMENT = "deployment"


class Principal(StrictModel):
    subject: str
    tenant_id: str
    roles: list[str] = Field(default_factory=lambda: ["reader"])

    def require(self, role: str) -> None:
        if role not in self.roles and "admin" not in self.roles:
            raise PermissionError(f"Required role: {role}")


class TraceContext(StrictModel):
    request_id: str = Field(default_factory=new_id)
    traceparent: str | None = None
    parent_request_id: str | None = None


class DocumentVersion(StrictModel):
    document_id: str
    version_id: str
    tenant_id: str
    sha256: str
    filename: str
    page_count: int
    created_at: str = Field(default_factory=utcnow)
    active: bool = True


class Chunk(StrictModel):
    chunk_id: str
    document_id: str
    version_id: str
    tenant_id: str
    page_number: int = Field(ge=1)
    page_label: str | None = None
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str


class Citation(StrictModel):
    chunk_id: str
    document_id: str
    version_id: str
    page_number: int = Field(ge=1)
    page_label: str | None = None
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    quote: str
    claim: str


class SearchHit(StrictModel):
    chunk: Chunk
    score: float
    lexical_rank: int | None = None
    dense_rank: int | None = None
    rerank_score: float | None = None


class Answer(StrictModel):
    message_id: str = Field(default_factory=new_id)
    request_id: str
    text: str
    citations: list[Citation] = Field(default_factory=list)
    abstained: bool = False
    conflicts: list[str] = Field(default_factory=list)
    profile: Profile
    model: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ModelRequest(StrictModel):
    request_id: str = Field(default_factory=new_id)
    principal: Principal
    messages: list[dict[str, str]]
    task_type: str = "answer"
    context_tokens: int = Field(default=0, ge=0)
    max_output_tokens: int = Field(default=512, ge=1, le=32768)
    required_capabilities: list[str] = Field(default_factory=list)
    quality: Literal["standard", "high"] = "standard"
    budget_microusd: int = Field(default=0, ge=0)


class ModelResponse(StrictModel):
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str


class UsageEvent(StrictModel):
    event_id: str = Field(default_factory=new_id)
    request_id: str
    attempt_id: str
    tenant_id: str
    kind: Literal[
        "reserved",
        "estimated",
        "reported",
        "reconciled",
        "released",
        "unknown",
        "correction",
        "cache",
    ]
    microusd: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    pricing_version: str
    timestamp: str = Field(default_factory=utcnow)


class Action(StrictModel):
    tool: str
    arguments: dict[str, Any]
    context_version: str
    idempotency_key: str


class Approval(StrictModel):
    approval_id: str = Field(default_factory=new_id)
    tenant_id: str
    requester: str
    reviewer: str
    action: Action
    action_hash: str
    expires_at: str
    status: Literal["pending", "approved", "rejected", "cancelled", "expired", "executed"] = (
        "pending"
    )


class Job(StrictModel):
    job_id: str = Field(default_factory=new_id)
    principal: Principal
    trace: TraceContext
    idempotency_key: str
    payload: dict[str, Any]
    status: Literal[
        "pending", "queued", "running", "retry", "succeeded", "dead", "cancelled", "uncertain"
    ] = "pending"
    attempts: int = 0


class EvalResult(StrictModel):
    case_id: str
    category: str
    passed: bool
    profile: Profile
    latency_ms: float = 0
    metrics: dict[str, float | None] = Field(default_factory=dict)
    error: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
