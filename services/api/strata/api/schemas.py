"""Pydantic v2 request/response schemas for /api/v1 (mirrored in apps/web/src/lib/types.ts)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
DatasetKind = Literal["g25", "raw_dna", "vcf"]
AnalysisKind = Literal[
    "pca_project", "nearest", "admixture_fit", "admixture_rotate", "qpadm", "qpadm_rotate"
]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ------------------------------------------------------------------ health / auth


class Capabilities(Schema):
    qpadm: bool = Field(description="R + ADMIXTOOLS 2 available for formal qpAdm tests")
    llm_providers: list[str] = Field(description="LLM providers with a configured API key")
    llm_configured: bool = Field(description="The selected STRATA_LLM_PROVIDER has a key")
    reference_version: str | None = Field(description="Loaded reference library version")
    reference_loaded: bool
    snp_panel_loaded: bool
    pca_space: str | None = None
    job_mode: str
    job_kinds: list[str]
    storage_backend: str
    database: str
    auth: dict[str, bool]
    examples: int


class Health(Schema):
    status: Literal["ok", "degraded"]
    version: str
    capabilities: Capabilities
    notes: list[str] = []


class GuestToken(Schema):
    token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: datetime
    owner_id: uuid.UUID


class Me(Schema):
    id: uuid.UUID
    kind: Literal["user", "guest"]
    email: str | None
    expires_at: datetime | None


# ------------------------------------------------------------------ datasets


class QCOut(Schema):
    model_config = ConfigDict(extra="allow")
    n_variants: int = 0
    warnings: list[str] = []


class DatasetOut(Schema):
    id: uuid.UUID
    name: str
    kind: DatasetKind
    space: str | None
    sample_names: list[str]
    created_at: datetime
    expires_at: datetime | None
    qc: dict[str, Any]
    summary: dict[str, Any] = {}
    input_sha256: str
    payload_sha256: str
    size_bytes: int


# ------------------------------------------------------------------ jobs / analyses


class JobOut(Schema):
    id: uuid.UUID
    kind: str
    status: JobStatus
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    attempts: int
    max_attempts: int
    analysis_id: uuid.UUID | None = None
    result: dict[str, Any] | None = None


class AnalysisCreate(Schema):
    kind: AnalysisKind
    title: str | None = Field(None, max_length=200)
    dataset_id: uuid.UUID | None = Field(
        None, description="User dataset providing the target (omit for reference-only runs)"
    )
    target: str | None = Field(
        None,
        max_length=200,
        description="Sample name within the dataset, or a reference population id",
    )
    params: dict[str, Any] = Field(default_factory=dict)


class AnalysisOut(Schema):
    id: uuid.UUID
    kind: AnalysisKind
    title: str | None
    status: JobStatus
    dataset_id: uuid.UUID | None
    dataset_ids: list[uuid.UUID]
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    provenance: dict[str, Any]
    job_id: uuid.UUID | None
    created_at: datetime
    finished_at: datetime | None
    expires_at: datetime | None


class AnalysisCreated(Schema):
    analysis: AnalysisOut
    job: JobOut


class ComparisonCreate(Schema):
    name: str = Field(max_length=200)
    analysis_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    notes: str | None = Field(None, max_length=10_000)


class ComparisonOut(Schema):
    id: uuid.UUID
    name: str
    analysis_ids: list[uuid.UUID]
    notes: str | None
    summary: dict[str, Any]
    created_at: datetime


# ------------------------------------------------------------------ examples


class ExampleSummary(Schema):
    model_config = ConfigDict(extra="allow")
    slug: str
    title: str
    summary: str
    kind: str
    result_kind: Literal["exploratory", "formal"]
    tags: list[str] = []


class ExampleDetail(ExampleSummary):
    description: str | None = None
    inputs: dict[str, Any] = {}
    params: dict[str, Any] = {}
    result: dict[str, Any]
    provenance: dict[str, Any] = {}


# ------------------------------------------------------------------ chat


class ChatSessionCreate(Schema):
    title: str | None = Field(None, max_length=200)
    dataset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class ChatMessageOut(Schema):
    id: uuid.UUID
    seq: int
    role: Literal["user", "assistant"]
    content: str
    tool_calls: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    grounding: dict[str, Any] | None
    citations: list[Any]
    usage: dict[str, Any] | None
    error: str | None
    created_at: datetime


class ChatSessionOut(Schema):
    id: uuid.UUID
    title: str | None
    dataset_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(ChatSessionOut):
    messages: list[ChatMessageOut]


class ChatMessageCreate(Schema):
    content: str = Field(min_length=1, max_length=8000)
