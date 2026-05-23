from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from zwmp_rule.types import DebugEvent, MediaType, ProjectionResult


JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class GenerationOptions(BaseModel):
    force_network_sniff: bool = False
    fast_mode: bool = True
    max_items: int | None = None
    sample_items: int = 8
    max_candidate_groups: int = 6
    validate_hypotheses: int = 5
    validation_limit: int = 24
    detail_probes: int = 3
    scroll_steps: int = 3
    desktop: bool = False


class GenerationRequest(BaseModel):
    url: HttpUrl
    media_type: MediaType = MediaType.VIDEO
    options: GenerationOptions = Field(default_factory=GenerationOptions)


class ProjectionRequest(BaseModel):
    rule_text: str | None = None


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
    kind: Literal["ai_fallback", "ai_quota", "sniffing_limited"]
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
    partial_result: dict[str, Any] | None = None
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
    generation_mode: str = "local"


class GenerationResult(BaseModel):
    rule_id: str
    rule_text: str
    site_profile: SiteProfile
    projection_preview: ProjectionResult
    cache_hit: bool = False
    alternatives: list[RuleDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)
    v3: dict[str, Any] = Field(default_factory=dict)


class ProjectionJobResult(BaseModel):
    projection: ProjectionResult
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)
    debug: dict[str, Any] = Field(default_factory=dict)


class PublicConfig(BaseModel):
    site: dict[str, Any]


class ShareCreateRequest(BaseModel):
    rule_text: str
    projection: ProjectionResult
    site_profile: SiteProfile | None = None
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ShareResponse(BaseModel):
    id: str
    url_path: str
    rule_text: str
    projection: ProjectionResult
    site_profile: SiteProfile | None = None
    runtime_notices: list[RuntimeNotice] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: str
