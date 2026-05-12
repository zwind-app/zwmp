from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from zwmp_rule import format_rule, parse_rule
from zwmp_rule.media import extension_for_url, extract_media_urls
from zwmp_rule.security import assert_public_http_url
from zwmp_rule.types import DebugEvent, ProjectionMedia, ProjectionResult
from zwmp_rule.projection import build_projection_tree

from .config import Settings
from .fetcher import PageFetcher
from .heuristics import analyze_site, build_projection_from_rule, choose_best_draft, extract_links_by_selector
from .ai import AIAnalyzer
from .schemas import (
    GenerationRequest,
    GenerationResult,
    JobResponse,
    ProjectionJobResult,
    ProjectionRequest,
    RuleDraft,
)
from .storage import Storage


class JobManager:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.fetcher = PageFetcher(settings)
        self.ai = AIAnalyzer(settings)
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
        options = request.options.model_dump()
        assert_public_http_url(url)
        job = self.jobs[job_id]
        cache_key = self.storage.cache_key(url, media_type, options)
        if not request.options.force_refresh:
            cached_id = self.storage.get_cached_rule_id(cache_key)
            if cached_id:
                rule_text = self.storage.get_rule_text(cached_id)
                if rule_text:
                    projection = await self._projection_for_rule(rule_text)
                    result = GenerationResult(
                        rule_id=cached_id,
                        rule_text=rule_text,
                        site_profile=analyze_site("", url, media_type)[0],
                        projection_preview=projection,
                        cache_hit=True,
                    )
                    return result.model_dump()

        self._update(job, "loading", 0.1, "Loading page in browser runtime")
        page = await self.fetcher.load(url)
        self._update(job, "mapping", 0.3, "Mapping page structure")
        profile, drafts, events = analyze_site(page.html, page.final_url, media_type)
        job.debug_events.extend(events)
        ai_suggestion = await self.ai.suggest_rule_fields(
            {
                "url": page.final_url,
                "media_type": media_type,
                "heuristic_drafts": [draft.model_dump() for draft in drafts[:3]],
                "events": [event.model_dump() for event in events],
            }
        )
        if ai_suggestion:
            job.debug_events.append(DebugEvent(phase="ai", message="AI returned a structured selector suggestion", data=ai_suggestion))
            profile.category = str(ai_suggestion.get("category") or profile.category)
        else:
            job.debug_events.append(DebugEvent(phase="ai", message="AI unavailable; using deterministic heuristics"))
        if not drafts:
            raise RuntimeError("No candidate selectors could be generated")

        self._update(job, "validating", 0.55, "Validating generated rule drafts")
        validated: list[RuleDraft] = []
        preview: ProjectionResult | None = None
        for draft in drafts[:4]:
            rule = parse_rule(draft.rule_text)
            projection = build_projection_from_rule(rule, page.html, page.final_url)
            score = draft.score
            if projection.items:
                score += 0.2
            if projection.media:
                score += 0.25
            validated.append(draft.model_copy(update={"score": round(min(score, 1.0), 3)}))
            if preview is None:
                preview = projection
        best = choose_best_draft(sorted(validated, key=lambda item: item.score, reverse=True), preview)
        best_rule = parse_rule(best.rule_text)
        if request.options.force_network_sniff:
            best_rule.force_network_sniff = True
        if request.options.fast_mode:
            best_rule.fast_mode = True
        if request.options.max_items:
            best_rule.max_items = request.options.max_items
        rule_text = format_rule(best_rule)
        preview = build_projection_from_rule(best_rule, page.html, page.final_url)
        preview = await self._probe_detail_pages(best_rule, preview)
        job.debug_events.extend(preview.debug_events)

        self._update(job, "saving", 0.85, "Saving generated rule")
        summary = self.storage.save_rule(rule_text, profile)
        self.storage.set_cache(cache_key, summary.id)
        self._register_proxy_media(job_id, preview)
        result = GenerationResult(
            rule_id=summary.id,
            rule_text=rule_text,
            site_profile=profile,
            projection_preview=preview,
            cache_hit=False,
            alternatives=validated,
            warnings=preview.warnings,
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
        projection = await self._projection_for_rule(rule_text)
        self._register_proxy_media(job_id, projection)
        return ProjectionJobResult(projection=projection).model_dump()

    async def _projection_for_rule(self, rule_text: str) -> ProjectionResult:
        rule = parse_rule(rule_text)
        page = await self.fetcher.load(str(rule.source), force_desktop=rule.force_desktop_mode or True)
        projection = build_projection_from_rule(rule, page.html, page.final_url)
        return await self._probe_detail_pages(rule, projection)

    async def _probe_detail_pages(self, rule, projection: ProjectionResult) -> ProjectionResult:
        if projection.media or not projection.items:
            return projection
        semaphore = asyncio.Semaphore(max(1, rule.max_detail_concurrency))

        async def probe(item):
            async with semaphore:
                try:
                    page = await self.fetcher.load(item.detail_url, force_desktop=rule.force_desktop_mode or True)
                except Exception as exc:
                    item.warning = f"Detail probe failed: {exc}"
                    return []
                urls = extract_media_urls(page.html, page.final_url, str(rule.media_type))
                if not urls and rule.detail_url_selector:
                    next_urls = extract_links_by_selector(
                        page.html,
                        page.final_url,
                        rule.detail_url_selector,
                        limit=1 if rule.detail_url_mode == "single" else 20,
                    )
                    for next_url in next_urls:
                        try:
                            next_page = await self.fetcher.load(next_url, force_desktop=rule.force_desktop_mode or True)
                        except Exception:
                            continue
                        urls.extend(extract_media_urls(next_page.html, next_page.final_url, str(rule.media_type)))
                found = []
                for url in urls[:3]:
                    media_id = f"media-{item.id}-{len(found) + 1}"
                    found.append(
                        ProjectionMedia(
                            id=media_id,
                            item_id=item.id,
                            url=url,
                            type=rule.media_type,
                            extension=extension_for_url(url) or "url",
                            delivery="direct",
                        )
                    )
                if found:
                    item.status = "resolved"
                    item.media_ids.extend(entry.id for entry in found)
                    item.warning = None
                return found

        tasks = [probe(item) for item in projection.items[: self.settings.probe_items]]
        results = await asyncio.gather(*tasks)
        for entries in results:
            projection.media.extend(entries)
        if projection.media:
            projection.warnings = [warning for warning in projection.warnings if "No direct media" not in warning]
        projection.tree = build_projection_tree(rule.projection, projection.items, projection.media)
        projection.debug_events.append(
            DebugEvent(
                phase="candidate-probe",
                message="Probed candidate detail pages for media URLs",
                data={"probed": min(len(projection.items), self.settings.probe_items), "media": len(projection.media)},
            )
        )
        return projection

    def _register_proxy_media(self, job_id: str, projection: ProjectionResult) -> None:
        for media in projection.media:
            self.proxy_media[f"{job_id}:{media.id}"] = {"url": media.url, **media.headers_hint}

    def proxy_target(self, session_id: str, media_id: str) -> dict[str, str] | None:
        return self.proxy_media.get(f"{session_id}:{media_id}")

    def _update(self, job: JobResponse, phase: str, progress: float, message: str) -> None:
        job.phase = phase
        job.progress = progress
        job.debug_events.append(DebugEvent(phase=phase, message=message))
