from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class Settings(BaseModel):
    data_dir: Path = Path(os.getenv("ZWMP_DATA_DIR", "data"))
    cache_db: Path = Path(os.getenv("ZWMP_CACHE_DB", "data/cache/zwmp.sqlite3"))
    rule_output_dir: Path = Path(os.getenv("ZWMP_RULE_OUTPUT_DIR", "data/generated-rules"))
    ai_provider: str = os.getenv("ZWMP_AI_PROVIDER", "none")
    ai_api_key: str | None = os.getenv("ZWMP_AI_API_KEY")
    ai_model: str = os.getenv("ZWMP_AI_MODEL", "gpt-4.1-mini")
    generator_version: str = "0.1.0"
    max_items: int = int(os.getenv("ZWMP_MAX_ITEMS", "30"))
    probe_items: int = int(os.getenv("ZWMP_PROBE_ITEMS", "3"))
    request_timeout_seconds: float = float(os.getenv("ZWMP_REQUEST_TIMEOUT", "12"))
    max_html_bytes: int = int(os.getenv("ZWMP_MAX_HTML_BYTES", str(2_000_000)))
    proxy_ttl_seconds: int = int(os.getenv("ZWMP_PROXY_TTL_SECONDS", "900"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_db.parent.mkdir(parents=True, exist_ok=True)
        self.rule_output_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()

