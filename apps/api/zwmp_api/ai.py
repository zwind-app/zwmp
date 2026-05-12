from __future__ import annotations

import json
from typing import Any

import httpx

from .config import Settings


class AIAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def available(self) -> bool:
        return bool(self.settings.ai_api_key and self.settings.ai_provider != "none")

    async def suggest_rule_fields(self, summary: dict[str, Any]) -> dict[str, Any] | None:
        if not self.available:
            return None
        base_url = self.settings.ai_provider.rstrip("/")
        payload = {
            "model": self.settings.ai_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You generate JSON for ZWMP .wm rule fields. Return only JSON with "
                        "candidate_selector, optional candidate_link_selector, optional title_selector, "
                        "optional thumbnail_selector, optional duration_selector, projection, category, notes."
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
            return json.loads(content)
        except json.JSONDecodeError:
            return None

