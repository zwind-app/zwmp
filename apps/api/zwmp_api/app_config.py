from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


QuotaScope = Literal["ip", "device_id"]
QuotaWindow = Literal["hour", "day"]


class QuotaRule(BaseModel):
    scope: QuotaScope = "device_id"
    window: QuotaWindow = "day"
    limit: int = 2


class AIProviderConfig(BaseModel):
    id: str
    base_url: str
    api_key: str | None = None
    api_key_env: str | None = None
    model: str
    quota: list[QuotaRule] | None = None

    def resolved_api_key(self) -> str | None:
        if self.api_key:
            return self.api_key
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None


class AIConfig(BaseModel):
    global_quota: list[QuotaRule] = Field(default_factory=lambda: [QuotaRule()])
    providers: list[AIProviderConfig] = Field(default_factory=list)


class LocalizedSEO(BaseModel):
    title: str
    description: str
    keywords: list[str] = Field(default_factory=list)


class SiteLinks(BaseModel):
    github: str
    zwind: str


class SiteConfig(BaseModel):
    default_locale: str = "en"
    supported_locales: list[str] = Field(default_factory=lambda: ["en", "zh"])
    links: SiteLinks = Field(
        default_factory=lambda: SiteLinks(
            github="https://github.com/zwind-app/zwmp",
            zwind="https://apps.apple.com/us/app/zwind-webdav-server-player/id6755239096",
        )
    )
    seo: dict[str, LocalizedSEO] = Field(default_factory=dict)
    guidance: dict[str, str] = Field(default_factory=dict)


class AppConfig(BaseModel):
    site: SiteConfig = Field(default_factory=SiteConfig)
    ai: AIConfig = Field(default_factory=AIConfig)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def load_app_config() -> AppConfig:
    path = Path(os.getenv("ZWMP_CONFIG", project_root() / "config" / "zwmp.config.json"))
    if not path.exists():
        return AppConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(data)
