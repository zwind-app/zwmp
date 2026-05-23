from __future__ import annotations

import asyncio
import logging
import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from zwmp_rule.security import assert_public_http_url
from zwmp_rule.types import DebugEvent, ProjectionResult

from .app_config import AIProviderConfig
from .config import Settings, app_config
from .schemas import GenerationRequest, GenerationResult, JobResponse, ProjectionJobResult, ProjectionRequest, RuleDraft, RuntimeNotice
from .storage import Storage, normalized_url_pattern
from .v3_adapter import generate_v3_rule, preview_v3


LOGGER = logging.getLogger("zwmp_api.jobs")


class JobCancelled(Exception):
    pass


@dataclass(frozen=True)
class ClientContext:
    ip: str
    device_id: str


@dataclass(frozen=True)
class AISelection:
    settings: Settings
    notice: RuntimeNotice | None = None
    ai_available: bool = False


class JobManager:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.jobs: dict[str, JobResponse] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self._chrome_quota = max(1, settings.chrome_headless_quota)
        self._chrome_slots = asyncio.Semaphore(self._chrome_quota)

    def create_generation_job(self, request: GenerationRequest, context: ClientContext) -> JobResponse:
        job_id = str(uuid.uuid4())
        job = JobResponse(id=job_id, type="generation", status="running", phase="accepted", progress=0.02)
        self.jobs[job_id] = job
        self.tasks[job_id] = asyncio.create_task(self._run_job(job_id, lambda: self._generate(job_id, request, context)))
        return job

    def create_projection_job(self, request: ProjectionRequest) -> JobResponse:
        job_id = str(uuid.uuid4())
        job = JobResponse(id=job_id, type="projection", status="running", phase="accepted", progress=0.02)
        self.jobs[job_id] = job
        self.tasks[job_id] = asyncio.create_task(self._run_job(job_id, lambda: self._project(job_id, request)))
        return job

    def get(self, job_id: str) -> JobResponse | None:
        return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> JobResponse | None:
        job = self.jobs.get(job_id)
        if not job:
            return None
        if job.status in {"queued", "running"}:
            job.status = "cancelled"
            job.phase = "cancelled"
            job.debug_events.append(DebugEvent(level="warning", phase="cancelled", message="Job was cancelled by the client"))
            LOGGER.info("JOB_CANCELLED job_id=%s type=%s", job.id, job.type)
            print(f"{local_timestamp()} JOB_CANCELLED job_id={job.id} type={job.type}", file=sys.stderr)
        return job

    async def _run_job(self, job_id: str, runner: Callable[[], Awaitable[dict]]) -> None:
        job = self.jobs[job_id]
        if job.status == "cancelled":
            return
        job.status = "running"
        try:
            result = await runner()
            if job.status == "cancelled":
                return
            job.result = result
            job.status = "succeeded"
            job.phase = "done"
            job.progress = 1.0
        except JobCancelled:
            job.status = "cancelled"
            job.phase = "cancelled"
            job.debug_events.append(DebugEvent(level="warning", phase="cancelled", message="Job stopped after cancellation"))
        except Exception as exc:
            if job.status == "cancelled":
                return
            job.status = "failed"
            job.error = str(exc)
            job.debug_events.append(DebugEvent(level="error", phase=job.phase, message=str(exc)))
        finally:
            self.tasks.pop(job_id, None)

    async def _generate(self, job_id: str, request: GenerationRequest, context: ClientContext) -> dict:
        url = str(request.url)
        media_type = str(request.media_type)
        assert_public_http_url(url)
        job = self.jobs[job_id]
        cache_key = self.storage.cache_key(url, media_type, request.options.model_dump())
        job.debug_events.append(
            DebugEvent(
                phase="cache",
                message="Checking mandatory normalized URL pattern cache",
                data={"normalized_url_pattern": normalized_url_pattern(url)},
            )
        )

        ai_selection = self._select_ai_settings(context)
        if ai_selection.notice:
            job.debug_events.append(DebugEvent(phase="ai-quota", message=ai_selection.notice.message))
        cached_id = self.storage.get_cached_rule_id(cache_key, "ai")
        cache_mode = "ai"
        if not cached_id and not ai_selection.ai_available:
            cached_id = self.storage.get_cached_rule_id(cache_key, "local")
            cache_mode = "local"
        if cached_id:
            rule_text = self.storage.get_rule_text(cached_id)
            if rule_text:
                current_rule_text = replace_source(rule_text, url)
                self._set_partial_rule(
                    job,
                    rule_text=current_rule_text,
                    site_profile=None,
                    runtime_notices=[],
                    warnings=[],
                    cache_hit=True,
                )
                preview = await self._preview_rule(current_rule_text, job, 0.12, 0.86)
                result = GenerationResult(
                    rule_id=cached_id,
                    rule_text=current_rule_text,
                    site_profile=preview["site_profile"],
                    projection_preview=preview["projection"],
                    cache_hit=True,
                    alternatives=[],
                    warnings=preview["projection"].warnings,
                    runtime_notices=preview["runtime_notices"],
                    v3=preview["debug"],
                )
                job.debug_events.append(DebugEvent(phase="cache", message=f"Using {cache_mode} rule cache"))
                return result.model_dump()

        self._update(job, "collecting-evidence", 0.12, "Collecting browser-rendered v3 listing evidence")
        generated = await self._run_browser_thread(
            job,
            "generate",
            generate_v3_rule,
            url,
            media_type,
            request.options,
            ai_selection.settings,
            self._progress_mapper(job, 0.12, 0.76),
        )
        runtime_notices = list(generated["runtime_notices"])
        if ai_selection.notice:
            runtime_notices.insert(0, ai_selection.notice)
        self._set_partial_rule(
            job,
            rule_text=generated["rule_text"],
            site_profile=generated["site_profile"],
            runtime_notices=runtime_notices,
            warnings=generated["warnings"],
            cache_hit=False,
            v3=generated["v3"],
        )
        self._update(job, "rule-ready", 0.77, "Rule text is ready")
        self._update(job, "saving", 0.78, "Saving v3 generated rule")
        generation_mode = "ai" if bool(generated["v3"].get("used_ai")) else "local"
        summary = self.storage.save_rule(generated["rule_text"], generated["site_profile"], generation_mode=generation_mode)
        self.storage.set_cache(cache_key, summary.id, generation_mode)
        self._update(job, "previewing", 0.82, "Rule is ready; previewing projected resources")
        preview_warnings: list[str] = []
        preview_runtime_notices: list[RuntimeNotice] = []
        try:
            preview = await self._preview_rule(generated["rule_text"], job, 0.82, 0.94)
            projection: ProjectionResult = preview["projection"]
            preview_runtime_notices = preview["runtime_notices"]
        except Exception as exc:  # noqa: BLE001
            LOGGER.exception("generation preview failed job_id=%s", job_id)
            preview_warnings.append(f"Preview failed after rule generation: {exc}")
            projection = ProjectionResult(warnings=preview_warnings)
            job.debug_events.append(DebugEvent(level="warning", phase="previewing", message=preview_warnings[-1]))
        job.debug_events.extend(projection.debug_events)
        result = GenerationResult(
            rule_id=summary.id,
            rule_text=generated["rule_text"],
            site_profile=generated["site_profile"],
            projection_preview=projection,
            cache_hit=False,
            alternatives=[RuleDraft.model_validate(item) for item in generated["alternatives"]],
            warnings=[*generated["warnings"], *projection.warnings],
            runtime_notices=[*runtime_notices, *preview_runtime_notices],
            v3=generated["v3"],
        )
        return result.model_dump()

    async def _project(self, job_id: str, request: ProjectionRequest) -> dict:
        if request.rule_text:
            rule_text = request.rule_text
        else:
            raise RuntimeError("rule_text is required")
        if not rule_text:
            raise RuntimeError("rule was not found")
        preview = await self._preview_rule(rule_text, self.jobs[job_id], 0.08, 0.92)
        projection: ProjectionResult = preview["projection"]
        return ProjectionJobResult(
            projection=projection,
            runtime_notices=preview["runtime_notices"],
            debug=preview["debug"],
        ).model_dump()

    async def _preview_rule(self, rule_text: str, job: JobResponse | None = None, start: float = 0.1, end: float = 0.9) -> dict:
        def progress(phase: str, fraction: float, message: str, data: dict | None = None) -> None:
            if job:
                self._ensure_running(job)
                self._update(job, phase, start + (end - start) * fraction, message)
                projection = (data or {}).get("projection_preview")
                if projection is not None:
                    self._set_partial_projection(job, projection)
                if "runtime_notices" in (data or {}):
                    self._set_partial_runtime_notices(job, (data or {}).get("runtime_notices") or [])

        cancel_check = (lambda: self._ensure_running(job)) if job else None
        return await self._run_browser_thread(job, "preview", preview_v3, rule_text, self.settings, progress, cancel_check)

    async def _run_browser_thread(self, job: JobResponse | None, operation: str, func: Callable[..., Any], *args: Any) -> Any:
        if job:
            self._ensure_running(job)
        if job and self._chrome_slots.locked():
            self._update(
                job,
                "waiting-browser",
                job.progress,
                f"Waiting for Chrome headless quota ({self._chrome_quota} concurrent job)",
            )
        async with self._chrome_slots:
            if job:
                self._ensure_running(job)
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(func, *args)
                if job:
                    self._ensure_running(job)
                return result
            finally:
                LOGGER.info(
                    "CHROME_SLOT_RELEASE operation=%s duration_ms=%.1f quota=%d",
                    operation,
                    (time.perf_counter() - started) * 1000,
                    self._chrome_quota,
                )

    def _update(self, job: JobResponse, phase: str, progress: float, message: str) -> None:
        job.phase = phase
        job.progress = progress
        job.debug_events.append(DebugEvent(phase=phase, message=message))
        LOGGER.info(
            "JOB_PROGRESS job_id=%s type=%s phase=%s progress=%.3f message=%s",
            job.id,
            job.type,
            phase,
            progress,
            message,
        )
        print(
            f"{local_timestamp()} JOB_PROGRESS job_id={job.id} type={job.type} phase={phase} progress={progress:.3f} message={message}",
            file=sys.stderr,
        )

    def _set_partial_rule(
        self,
        job: JobResponse,
        *,
        rule_text: str,
        site_profile: object | None,
        runtime_notices: list[RuntimeNotice],
        warnings: list[str],
        cache_hit: bool,
        v3: dict | None = None,
    ) -> None:
        job.partial_result = {
            "rule_text": rule_text,
            "site_profile": site_profile.model_dump() if hasattr(site_profile, "model_dump") else site_profile,
            "runtime_notices": [notice.model_dump() if hasattr(notice, "model_dump") else notice for notice in runtime_notices],
            "warnings": warnings,
            "cache_hit": cache_hit,
            "v3": v3 or {},
        }

    def _set_partial_projection(self, job: JobResponse, projection: Any) -> None:
        current = dict(job.partial_result or {})
        current["projection_preview"] = projection.model_dump() if hasattr(projection, "model_dump") else projection
        job.partial_result = current

    def _set_partial_runtime_notices(self, job: JobResponse, notices: list[Any]) -> None:
        current = dict(job.partial_result or {})
        current["runtime_notices"] = [notice.model_dump() if hasattr(notice, "model_dump") else notice for notice in notices]
        job.partial_result = current

    def _ensure_running(self, job: JobResponse | None) -> None:
        if job and job.status == "cancelled":
            raise JobCancelled()

    def _progress_mapper(self, job: JobResponse, start: float, end: float):
        last_emit = {"time": 0.0, "phase": ""}

        def progress(phase: str, fraction: float, message: str, data: dict | None = None) -> None:
            self._ensure_running(job)
            now = time.perf_counter()
            # Always emit phase changes and validation milestones; throttle repetitive probes lightly.
            important = phase != last_emit["phase"] or phase.startswith(("validated", "validate-detail", "finalize", "rule-ready"))
            if important or now - last_emit["time"] >= 0.5:
                mapped = start + (end - start) * max(0.0, min(1.0, fraction))
                job.phase = phase
                job.progress = mapped
                job.debug_events.append(DebugEvent(phase=phase, message=message, data=data or {}))
                LOGGER.info(
                    "JOB_PROGRESS job_id=%s type=%s phase=%s progress=%.3f message=%s data=%s",
                    job.id,
                    job.type,
                    phase,
                    mapped,
                    message,
                    data or {},
                )
                print(
                    (
                        f"{local_timestamp()} JOB_PROGRESS job_id={job.id} type={job.type} phase={phase} "
                        f"progress={mapped:.3f} message={message} data={json.dumps(data or {}, ensure_ascii=False, default=str)}"
                    ),
                    file=sys.stderr,
                )
                last_emit["time"] = now
                last_emit["phase"] = phase

        return progress

    def _select_ai_settings(self, context: ClientContext) -> AISelection:
        providers = configured_ai_providers(self.settings)
        if not providers:
            return AISelection(self.settings.model_copy(update={"ai_provider": "none", "ai_api_key": None}), ai_available=False)
        subjects = {"ip": context.ip, "device_id": context.device_id}
        denied: list[str] = []
        for provider in providers:
            api_key = provider.resolved_api_key()
            if not api_key:
                denied.append(f"{provider.id}:missing-key")
                continue
            rules = provider.quota if provider.quota is not None else app_config.ai.global_quota
            allowed, reason = self.storage.reserve_ai_quota(provider.id, subjects, rules)
            if not allowed:
                denied.append(reason or provider.id)
                continue
            return AISelection(
                self.settings.model_copy(
                    update={
                        "ai_provider": provider.base_url,
                        "ai_api_key": api_key,
                        "ai_model": provider.model,
                    }
                ),
                ai_available=True,
            )
        notice = RuntimeNotice(
            kind="ai_quota",
            message="AI quota is exhausted or all configured providers are unavailable; local v3 hypotheses were used.",
            action="Wait for quota reset, self-host with a higher quota, or configure additional AI providers.",
        )
        return AISelection(self.settings.model_copy(update={"ai_provider": "none", "ai_api_key": None}), notice, ai_available=False)


def configured_ai_providers(settings: Settings) -> list[AIProviderConfig]:
    if app_config.ai.providers:
        return app_config.ai.providers
    if settings.ai_provider and settings.ai_provider != "none" and settings.ai_api_key:
        return [
            AIProviderConfig(
                id="env",
                base_url=settings.ai_provider,
                api_key=settings.ai_api_key,
                model=settings.ai_model,
                quota=None,
            )
        ]
    return []


def replace_source(rule_text: str, source_url: str) -> str:
    lines = rule_text.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("source="):
            lines[index] = f"source={source_url}"
            return "\n".join(lines) + ("\n" if rule_text.endswith("\n") else "")
    return f"source={source_url}\n{rule_text}"


def local_timestamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime())
