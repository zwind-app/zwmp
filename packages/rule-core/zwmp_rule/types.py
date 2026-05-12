from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class MediaType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    IMAGE = "image"
    ALL = "all"


class Projection(StrEnum):
    BY_ITEM = "by-item"
    FLAT = "flat"


class MediaDelivery(StrEnum):
    AUTO = "auto"
    PROXY = "proxy"


class WebMediaRule(BaseModel):
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    source: HttpUrl
    candidate_selector: str
    candidate_link_selector: str | None = None
    title_selector: str | None = None
    thumbnail_selector: str | None = None
    duration_selector: str | None = None
    projection: Projection = Projection.BY_ITEM
    media_type: MediaType = MediaType.VIDEO
    media_url_ttl: int | None = None
    media_delivery: MediaDelivery = MediaDelivery.AUTO
    max_items: int | None = None
    force_network_sniff: bool = False
    fast_mode: bool = False
    force_desktop_mode: bool = False

    @field_validator("candidate_selector")
    @classmethod
    def selector_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("candidate_selector is required")
        return value.strip()

    @field_validator("media_url_ttl", "max_items")
    @classmethod
    def non_negative_int(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("value must be non-negative")
        return value


class DebugEvent(BaseModel):
    level: Literal["debug", "info", "warning", "error"] = "info"
    phase: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class ProjectionMedia(BaseModel):
    id: str
    item_id: str
    url: str
    type: MediaType
    extension: str | None = None
    delivery: Literal["direct", "proxy", "auto"] = "direct"
    requires_proxy: bool = False
    headers_hint: dict[str, str] = Field(default_factory=dict)


class ProjectionItem(BaseModel):
    id: str
    title: str
    detail_url: str
    thumbnail_url: str | None = None
    duration: str | None = None
    status: Literal["pending", "resolved", "needs-interaction", "failed"] = "pending"
    media_ids: list[str] = Field(default_factory=list)
    warning: str | None = None


class ProjectionNode(BaseModel):
    id: str
    name: str
    kind: Literal["directory", "file"]
    item_id: str | None = None
    media_id: str | None = None
    children: list["ProjectionNode"] = Field(default_factory=list)


class ProjectionResult(BaseModel):
    tree: list[ProjectionNode] = Field(default_factory=list)
    items: list[ProjectionItem] = Field(default_factory=list)
    media: list[ProjectionMedia] = Field(default_factory=list)
    debug_events: list[DebugEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

