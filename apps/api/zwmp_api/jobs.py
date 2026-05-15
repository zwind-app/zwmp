from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from zwmp_rule.security import assert_public_http_url
from zwmp_rule.types import DebugEvent, ProjectionResult

from .config import Settings
from .schemas import GenerationRequest, GenerationResult, JobResponse, ProjectionJobResult, ProjectionRequest, RuleDraft
from .storage import Storage
from .v3_adapter import generate_v3, preview_v3


class JobManager:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.jobs: dict[str, JobResponse] = {}
        self.proxy_media: dict[str, dict[str, str]] = {}

    def create_generation_job(self, request: GenerationRequest) -> JobResponse:
        job_id = str(uuid.uuid4())
        job = JobResponse(id=job_id, type="generation", status="queued")
        self.jobs[job_id] = job
        asyncio.create_task(self._run_job(job_id, lambda: self._generate(job_id, request)))
        return job

    def create_projection_job(self, request: ProjectionRequest) -> JobResponse:
        job_id = str(uuid.uuid4())
        job = JobResponse(id=job_id, type="projection", status="queued")
        self.jobs[job_id] = job
        asyncio.create_task(self._run_job(job_id, lambda: self._project(job_id, request)))
        return job

    def get(self, job_id: str) -> JobResponse | None:
        return self.jobs.get(job_id)

    async def _run_job(self, job_id: str, runner: Callable[[], Awaitable[dict]]) -> None:
        job = self.jobs[job_id]
        job.status = "running"
        try:
            job.result = await runner()
            job.status = "succeeded"
            job.phase = "done"
            job.progress = 1.0
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            job.debug_events.append(DebugEvent(level="error", phase=job.phase, message=str(exc)))

    async def _generate(self, job_id: str, request: GenerationRequest) -> dict:
        url = str(request.url)
        media_type = str(request.media_type)
        assert_public_http_url(url)
        job = self.jobs[job_id]
        cache_key = self.storage.cache_key(url, media_type, request.options.model_dump())

        if not request.options.force_refresh:
            cached_id = self.storage.get_cached_rule_id(cache_key)
            if cached_id:
                rule_text = self.storage.get_rule_text(cached_id)
                if rule_text:
                    preview = await self._preview_rule(rule_text)
                    result = GenerationResult(
                        rule_id=cached_id,
                        rule_text=rule_text,
                        site_profile=preview["site_profile"],
                        projection_preview=preview["projection"],
                        cache_hit=True,
                        alternatives=[],
                        warnings=preview["projection"].warnings,
                        runtime_notices=preview["runtime_notices"],
                        v3=preview["debug"],
                    )
                    return result.model_dump()

        self._update(job, "collecting-evidence", 0.12, "Collecting browser-rendered v3 listing evidence")
        generated = await asyncio.to_thread(generate_v3, url, media_type, request.options, self.settings)
        projection: ProjectionResult = generated["projection"]
        job.debug_events.extend(projection.debug_events)
        self._update(job, "saving", 0.88, "Saving v3 generated rule")
        summary = self.storage.save_rule(generated["rule_text"], generated["site_profile"])
        self.storage.set_cache(cache_key, summary.id)
        self._register_proxy_media(job_id, projection)
        result = GenerationResult(
            rule_id=summary.id,
            rule_text=generated["rule_text"],
            site_profile=generated["site_profile"],
            projection_preview=projection,
            cache_hit=False,
            alternatives=[RuleDraft.model_validate(item) for item in generated["alternatives"]],
            warnings=generated["warnings"],
            runtime_notices=generated["runtime_notices"],
            v3=generated["v3"],
        )
        return result.model_dump()

    async def _project(self, job_id: str, request: ProjectionRequest) -> dict:
        if request.rule_text:
            rule_text = request.rule_text
        elif request.rule_id:
            rule_text = self.storage.get_rule_text(request.rule_id) or ""
        else:
            raise RuntimeError("rule_text or rule_id is required")
        if not rule_text:
            raise RuntimeError("rule was not found")
        preview = await self._preview_rule(rule_text)
        projection: ProjectionResult = preview["projection"]
        self._register_proxy_media(job_id, projection)
        return ProjectionJobResult(
            projection=projection,
            runtime_notices=preview["runtime_notices"],
            debug=preview["debug"],
        ).model_dump()

    async def _preview_rule(self, rule_text: str) -> dict:
        return await asyncio.to_thread(preview_v3, rule_text, self.settings)

    def _register_proxy_media(self, job_id: str, projection: ProjectionResult) -> None:
        for media in projection.media:
            self.proxy_media[f"{job_id}:{media.id}"] = {"url": media.url, **media.headers_hint}

    def proxy_target(self, session_id: str, media_id: str) -> dict[str, str] | None:
        return self.proxy_media.get(f"{session_id}:{media_id}")

    def _update(self, job: JobResponse, phase: str, progress: float, message: str) -> None:
        job.phase = phase
        job.progress = progress
        job.debug_events.append(DebugEvent(phase=phase, message=message))
