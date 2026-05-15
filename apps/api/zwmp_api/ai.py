from __future__ import annotations

import json
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from .config import Settings


class AIAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.ai_api_key and self.settings.ai_provider != "none")

    async def suggest_rule_fields(self, summary: dict[str, Any]) -> "AIRuleSuggestion | None":
        if not self.available:
            return None
        base_url = self.settings.ai_provider.rstrip("/")
        payload = {
            "model": self.settings.ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate JSON for ZWMP .wm rule fields. Return only JSON matching this schema: "
                        "{candidate_selector: string, candidate_link_selector?: string, title_selector?: string, "
                        "thumbnail_selector?: string, duration_selector?: string, detail_url_selector?: string, "
                        "detail_url_mode?: 'single'|'expand', projection: 'by-item'|'flat', category: string, "
                        "confidence: number, notes?: string}. Prefer selectors that are stable and specific."
                    ),
                },
                {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
            ],
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self.settings.ai_api_key}"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{base_url}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        try:
            return AIRuleSuggestion.model_validate(json.loads(content))
        except (json.JSONDecodeError, ValidationError):
            return None


class AIRuleSuggestion(BaseModel):
    candidate_selector: str
    candidate_link_selector: str | None = None
    title_selector: str | None = None
    thumbnail_selector: str | None = None
    duration_selector: str | None = None
    detail_url_selector: str | None = None
    detail_url_mode: Literal["single", "expand"] = "single"
    projection: Literal["by-item", "flat"] = "by-item"
    category: str = "media"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str | None = None
