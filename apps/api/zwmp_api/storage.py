from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from zwmp_rule.parser import parse_rule
from zwmp_rule.types import ProjectionResult

from .app_config import QuotaRule
from .config import Settings
from .schemas import RuntimeNotice, RuleSummary, ShareResponse, SiteProfile


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
                  cache_key TEXT NOT NULL,
                  generation_mode TEXT NOT NULL DEFAULT 'local',
                  rule_id TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  generator_version TEXT NOT NULL,
                  PRIMARY KEY(cache_key, generation_mode)
                );
                CREATE TABLE IF NOT EXISTS generated_rules (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  host TEXT NOT NULL,
                  media_type TEXT NOT NULL,
                  category TEXT NOT NULL,
                  rule_path TEXT NOT NULL,
                  metadata_path TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  generation_mode TEXT NOT NULL DEFAULT 'local'
                );
                CREATE TABLE IF NOT EXISTS ai_usage (
                  provider_id TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  subject TEXT NOT NULL,
                  window TEXT NOT NULL,
                  bucket TEXT NOT NULL,
                  count INTEGER NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(provider_id, scope, subject, window, bucket)
                );
                CREATE TABLE IF NOT EXISTS share_links (
                  id TEXT PRIMARY KEY,
                  rule_text TEXT NOT NULL,
                  projection_json TEXT NOT NULL,
                  site_profile_json TEXT,
                  runtime_notices_json TEXT NOT NULL,
                  warnings_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "generation_cache", "generation_mode", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(conn, "generated_rules", "generation_mode", "TEXT NOT NULL DEFAULT 'local'")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = [str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def cache_key(self, url: str, media_type: str, options: dict[str, object]) -> str:
        payload = {
            "normalized_url_pattern": normalized_url_pattern(url),
            "media_type": media_type,
            "generator_version": self.settings.generator_version,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    def get_cached_rule_id(self, cache_key: str, generation_mode: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rule_id FROM generation_cache WHERE cache_key = ? AND generation_mode = ?",
                (cache_key, generation_mode),
            ).fetchone()
        return str(row["rule_id"]) if row else None

    def set_cache(self, cache_key: str, rule_id: str, generation_mode: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generation_cache(cache_key, generation_mode, rule_id, created_at, generator_version)
                VALUES (?, ?, ?, ?, ?)
                """,
                (cache_key, generation_mode, rule_id, now_iso(), self.settings.generator_version),
            )

    def save_rule(self, rule_text: str, site_profile: SiteProfile, generation_mode: str = "local") -> RuleSummary:
        rule = parse_rule(rule_text)
        source = str(rule.source)
        parsed = urlparse(source)
        host = slug(parsed.hostname or "unknown")
        media_type = str(rule.media_type)
        category = slug(site_profile.category)
        created_at = now_iso()
        digest = hashlib.sha1(f"{source}|{media_type}|{rule_text}".encode()).hexdigest()[:12]
        rule_id = f"{host}-{media_type}-{digest}"
        mode = "ai" if generation_mode == "ai" else "local"
        directory = self.settings.rule_output_dir / mode / slug(media_type) / category / host
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
            "generation_mode": mode,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO generated_rules
                (id, source, host, media_type, category, rule_path, metadata_path, created_at, generation_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (rule_id, source, host, media_type, category, str(rule_path), str(metadata_path), created_at, mode),
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
            generation_mode=mode,
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
                generation_mode=row["generation_mode"] if "generation_mode" in row.keys() else "local",
            )
            for row in rows
        ]

    def reserve_ai_quota(self, provider_id: str, subjects: dict[str, str], rules: list[QuotaRule]) -> tuple[bool, str | None]:
        if not rules:
            return True, None
        buckets = [(rule, subjects.get(rule.scope, "unknown"), quota_bucket(rule.window)) for rule in rules]
        with self._connect() as conn:
            for rule, subject, bucket in buckets:
                row = conn.execute(
                    """
                    SELECT count FROM ai_usage
                    WHERE provider_id = ? AND scope = ? AND subject = ? AND window = ? AND bucket = ?
                    """,
                    (provider_id, rule.scope, subject, rule.window, bucket),
                ).fetchone()
                current = int(row["count"]) if row else 0
                if current >= rule.limit:
                    return False, f"{provider_id}:{rule.scope}:{rule.window}"
            for rule, subject, bucket in buckets:
                conn.execute(
                    """
                    INSERT INTO ai_usage(provider_id, scope, subject, window, bucket, count, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(provider_id, scope, subject, window, bucket)
                    DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
                    """,
                    (provider_id, rule.scope, subject, rule.window, bucket, now_iso()),
                )
        return True, None

    def create_share(
        self,
        rule_text: str,
        projection: ProjectionResult,
        site_profile: SiteProfile | None,
        runtime_notices: list[RuntimeNotice],
        warnings: list[str],
    ) -> ShareResponse:
        created_at = now_iso()
        digest = hashlib.sha1(f"{created_at}|{rule_text}".encode()).hexdigest()[:16]
        share_id = f"s-{digest}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO share_links
                (id, rule_text, projection_json, site_profile_json, runtime_notices_json, warnings_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    share_id,
                    rule_text,
                    projection.model_dump_json(),
                    site_profile.model_dump_json() if site_profile else None,
                    json.dumps([notice.model_dump() for notice in runtime_notices], ensure_ascii=False),
                    json.dumps(warnings, ensure_ascii=False),
                    created_at,
                ),
            )
        return ShareResponse(
            id=share_id,
            url_path=f"/?share={share_id}",
            rule_text=rule_text,
            projection=projection,
            site_profile=site_profile,
            runtime_notices=runtime_notices,
            warnings=warnings,
            created_at=created_at,
        )

    def get_share(self, share_id: str) -> ShareResponse | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM share_links WHERE id = ?", (share_id,)).fetchone()
        if not row:
            return None
        site_profile = SiteProfile.model_validate_json(row["site_profile_json"]) if row["site_profile_json"] else None
        runtime_notices = [RuntimeNotice.model_validate(item) for item in json.loads(row["runtime_notices_json"])]
        return ShareResponse(
            id=row["id"],
            url_path=f"/?share={row['id']}",
            rule_text=row["rule_text"],
            projection=ProjectionResult.model_validate_json(row["projection_json"]),
            site_profile=site_profile,
            runtime_notices=runtime_notices,
            warnings=[str(item) for item in json.loads(row["warnings_json"])],
            created_at=row["created_at"],
        )


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def normalized_url_pattern(url: str) -> str:
    parsed = urlparse(url)
    query_keys = [(key, "") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
    query = urlencode(query_keys, doseq=True)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=query,
        fragment="",
    )
    return urlunparse(normalized)


def quota_bucket(window: str) -> str:
    now = datetime.now(UTC)
    if window == "hour":
        return now.strftime("%Y%m%d%H")
    return now.strftime("%Y%m%d")
