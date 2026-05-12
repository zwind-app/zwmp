from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from zwmp_rule.parser import parse_rule

from .config import Settings
from .schemas import RuleSummary, SiteProfile


def slug(value: str, fallback: str = "unknown") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._").lower()
    return cleaned[:80] or fallback


class Storage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.settings.ensure_dirs()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.settings.cache_db)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS generation_cache (
                  cache_key TEXT PRIMARY KEY,
                  rule_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  generator_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS generated_rules (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  host TEXT NOT NULL,
                  media_type TEXT NOT NULL,
                  category TEXT NOT NULL,
                  rule_path TEXT NOT NULL,
                  metadata_path TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )

    def cache_key(self, url: str, media_type: str, options: dict[str, object]) -> str:
        payload = {
            "url": url,
            "media_type": media_type,
            "options": options,
            "generator_version": self.settings.generator_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get_cached_rule_id(self, cache_key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT rule_id FROM generation_cache WHERE cache_key = ?", (cache_key,)).fetchone()
        return str(row["rule_id"]) if row else None

    def set_cache(self, cache_key: str, rule_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO generation_cache(cache_key, rule_id, created_at, generator_version) VALUES (?, ?, ?, ?)",
                (cache_key, rule_id, now_iso(), self.settings.generator_version),
            )

    def save_rule(self, rule_text: str, site_profile: SiteProfile) -> RuleSummary:
        rule = parse_rule(rule_text)
        source = str(rule.source)
        parsed = urlparse(source)
        host = slug(parsed.hostname or "unknown")
        media_type = str(rule.media_type)
        category = slug(site_profile.category)
        created_at = now_iso()
        digest = hashlib.sha1(f"{source}|{media_type}|{rule_text}".encode()).hexdigest()[:12]
        rule_id = f"{host}-{media_type}-{digest}"
        directory = self.settings.rule_output_dir / slug(media_type) / category / host
        directory.mkdir(parents=True, exist_ok=True)
        rule_path = directory / f"{rule_id}.wm"
        metadata_path = directory / f"{rule_id}.json"
        rule_path.write_text(rule_text, encoding="utf-8")
        metadata = {
            "id": rule_id,
            "source": source,
            "host": host,
            "media_type": media_type,
            "site_profile": site_profile.model_dump(),
            "created_at": created_at,
            "generator_version": self.settings.generator_version,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generated_rules
                (id, source, host, media_type, category, rule_path, metadata_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_id, source, host, media_type, category, str(rule_path), str(metadata_path), created_at),
            )
        return RuleSummary(
            id=rule_id,
            source=source,
            host=host,
            media_type=media_type,
            category=category,
            rule_path=str(rule_path),
            metadata_path=str(metadata_path),
            created_at=created_at,
        )

    def get_rule_text(self, rule_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute("SELECT rule_path FROM generated_rules WHERE id = ?", (rule_id,)).fetchone()
        if not row:
            return None
        path = Path(str(row["rule_path"]))
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def list_rules(self) -> list[RuleSummary]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM generated_rules ORDER BY created_at DESC").fetchall()
        return [
            RuleSummary(
                id=row["id"],
                source=row["source"],
                host=row["host"],
                media_type=row["media_type"],
                category=row["category"],
                rule_path=row["rule_path"],
                metadata_path=row["metadata_path"],
                created_at=row["created_at"],
            )
            for row in rows
        ]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()

