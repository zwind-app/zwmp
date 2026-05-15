from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from zwmp_rule.types import DebugEvent, MediaType, ProjectionResult


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class GenerationOptions(BaseModel):
    force_refresh: bool = False
    force_network_sniff: bool = False
    fast_mode: bool = False
    max_items: int | None = None


class GenerationRequest(BaseModel):
    url: HttpUrl
    media_type: MediaType = MediaType.VIDEO
    options: GenerationOptions = Field(default_factory=GenerationOptions)


class ProjectionRequest(BaseModel):
    rule_text: str | None = None
    rule_id: str | None = None


class SiteProfile(BaseModel):
    category: str = "unknown"
    language: str = "unknown"
    layout_type: str = "unknown"
    content_type: str = "unknown"
    confidence: float = 0.0
    notes: str | None = None


class RuleDraft(BaseModel):
    rule_text: str
    score: float
    reason: str


class RuntimeNotice(BaseModel):
    kind: Literal["ai_fallback", "browser_fallback", "sniffing_limited"]
    message: str
    action: str


class JobResponse(BaseModel):
    id: str
    type: Literal["generation", "projection"]
    status: JobStatus
    phase: str = "queued"
    progress: float = 0.0
    error: str | None = None
    debug_events: list[DebugEvent] = Field(default_factory=list)
    result: dict[str, Any] | None = None


class RuleSummary(BaseModel):
    id: str
    source: str
    host: str
    media_type: str
    category: str
    rule_path: str
    metadata_path: str
    created_at: str


class GenerationResult(BaseModel):
    rule_id: str
    rule_text: str
    site_profile: SiteProfile
    projection_preview: ProjectionResult
    cache_hit: bool = False
    alternatives: list[RuleDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)


class ProjectionJobResult(BaseModel):
    projection: ProjectionResult
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)
