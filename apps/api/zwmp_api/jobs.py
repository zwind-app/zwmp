from __future__ import annotations

import asyncio
import uuid
from typing import Awaitable, Callable

from zwmp_rule import format_rule, parse_rule
from zwmp_rule.media import extension_for_url, extract_media_urls
from zwmp_rule.security import assert_public_http_url
from zwmp_rule.types import DebugEvent, ProjectionItem, ProjectionMedia, ProjectionResult, WebMediaRule
from zwmp_rule.projection import build_projection_tree

from .config import Settings
from .fetcher import PageFetcher
from .heuristics import analyze_site, build_projection_from_rule, choose_best_draft, extract_links_by_selector, title_from_url
from .ai import AIAnalyzer
from .schemas import (
    GenerationRequest,
    GenerationResult,
    JobResponse,
    ProjectionJobResult,
    ProjectionRequest,
    RuleDraft,
    RuntimeNotice,
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
                    projection, projection_notices = await self._projection_for_rule(rule_text)
                    result = GenerationResult(
                        rule_id=cached_id,
                        rule_text=rule_text,
                        site_profile=analyze_site("", url, media_type)[0],
                        projection_preview=projection,
                        cache_hit=True,
                        runtime_notices=projection_notices,
                    )
                    return result.model_dump()

        self._update(job, "loading", 0.1, "Loading page in browser runtime")
        page = await self.fetcher.load(url, fast_mode=request.options.fast_mode)
        self._update(job, "mapping", 0.3, "Mapping page structure")
        profile, drafts, events = analyze_site(page.html, page.final_url, media_type)
        job.debug_events.extend(events)
        try:
            ai_suggestion = await self.ai.suggest_rule_fields(
                {
                    "url": page.final_url,
                    "media_type": media_type,
                    "heuristic_drafts": [draft.model_dump() for draft in drafts[:3]],
                    "events": [event.model_dump() for event in events],
                }
            )
        except Exception as exc:
            ai_suggestion = None
            job.debug_events.append(DebugEvent(level="warning", phase="ai", message=f"AI analysis failed; using heuristics: {exc}"))
        if ai_suggestion:
            job.debug_events.append(DebugEvent(phase="ai", message="AI returned a structured selector suggestion", data=ai_suggestion.model_dump()))
            profile.category = ai_suggestion.category or profile.category
            ai_rule = WebMediaRule(
                source=page.final_url,
                candidate_selector=ai_suggestion.candidate_selector,
                candidate_link_selector=ai_suggestion.candidate_link_selector,
                detail_url_selector=ai_suggestion.detail_url_selector,
                detail_url_mode=ai_suggestion.detail_url_mode,
                title_selector=ai_suggestion.title_selector,
                thumbnail_selector=ai_suggestion.thumbnail_selector,
                duration_selector=ai_suggestion.duration_selector,
                projection=ai_suggestion.projection,
                media_type=media_type,
                max_items=request.options.max_items or self.settings.max_items,
            )
            drafts.insert(0, RuleDraft(rule_text=format_rule(ai_rule), score=0.7 + ai_suggestion.confidence * 0.25, reason="ai structured suggestion"))
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
        self._add_network_media(best_rule, preview, page.network_media)
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
            runtime_notices=self._runtime_notices(ai_used=ai_suggestion is not None, browser_used=page.browser_used, browser_reason=page.fallback_reason, sniff_requested=request.options.force_network_sniff),
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
        projection, runtime_notices = await self._projection_for_rule(rule_text)
        self._register_proxy_media(job_id, projection)
        return ProjectionJobResult(projection=projection, runtime_notices=runtime_notices).model_dump()

    async def _projection_for_rule(self, rule_text: str) -> tuple[ProjectionResult, list[RuntimeNotice]]:
        rule = parse_rule(rule_text)
        page = await self.fetcher.load(str(rule.source), force_desktop=rule.force_desktop_mode or True, fast_mode=rule.fast_mode)
        projection = build_projection_from_rule(rule, page.html, page.final_url)
        self._add_network_media(rule, projection, page.network_media)
        projection = await self._probe_detail_pages(rule, projection)
        return projection, self._runtime_notices(
            ai_used=self.ai.available,
            browser_used=page.browser_used,
            browser_reason=page.fallback_reason,
            sniff_requested=rule.force_network_sniff,
        )

    async def _probe_detail_pages(self, rule: WebMediaRule, projection: ProjectionResult) -> ProjectionResult:
        if projection.media or not projection.items:
            return projection
        if rule.detail_url_selector and rule.detail_url_mode == "expand":
            expanded = await self._expand_detail_items(rule, projection)
            if expanded.media or len(expanded.items) != len(projection.items):
                return expanded
        semaphore = asyncio.Semaphore(max(1, rule.max_detail_concurrency))

        async def probe(item):
            async with semaphore:
                try:
                    page = await self.fetcher.load(item.detail_url, force_desktop=rule.force_desktop_mode or True, fast_mode=rule.fast_mode)
                except Exception as exc:
                    item.warning = f"Detail probe failed: {exc}"
                    return []
                urls = extract_media_urls(page.html, page.final_url, str(rule.media_type))
                if (not urls or not rule.detail_url_stop_when_media_found) and rule.detail_url_selector:
                    urls.extend(await self._resolve_detail_chain(rule, page.html, page.final_url))
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

    async def _expand_detail_items(self, rule: WebMediaRule, projection: ProjectionResult) -> ProjectionResult:
        expanded_items: list[ProjectionItem] = []
        expanded_media: list[ProjectionMedia] = []
        for parent in projection.items[: self.settings.probe_items]:
            try:
                page = await self.fetcher.load(parent.detail_url, force_desktop=rule.force_desktop_mode or True, fast_mode=rule.fast_mode)
            except Exception as exc:
                parent.warning = f"Detail expansion failed: {exc}"
                expanded_items.append(parent)
                continue
            next_urls = extract_links_by_selector(page.html, page.final_url, rule.detail_url_selector, limit=self.settings.max_items)
            if not next_urls:
                expanded_items.append(parent)
                continue
            for index, next_url in enumerate(next_urls, start=1):
                item_id = f"{parent.id}-episode-{index}"
                item = ProjectionItem(
                    id=item_id,
                    title=f"{parent.title} / {title_from_url(next_url)}",
                    detail_url=next_url,
                    thumbnail_url=parent.thumbnail_url,
                    status="pending",
                )
                try:
                    next_page = await self.fetcher.load(next_url, force_desktop=rule.force_desktop_mode or True, fast_mode=rule.fast_mode)
                except Exception as exc:
                    item.warning = f"Expanded item probe failed: {exc}"
                    expanded_items.append(item)
                    continue
                urls = extract_media_urls(next_page.html, next_page.final_url, str(rule.media_type))
                for media_index, url in enumerate(urls[:3], start=1):
                    media_id = f"media-{item_id}-{media_index}"
                    expanded_media.append(
                        ProjectionMedia(
                            id=media_id,
                            item_id=item.id,
                            url=url,
                            type=rule.media_type,
                            extension=extension_for_url(url) or "url",
                            delivery="direct",
                        )
                    )
                    item.media_ids.append(media_id)
                    item.status = "resolved"
                if not urls:
                    item.status = "needs-interaction"
                    item.warning = "Expanded item did not expose direct media."
                expanded_items.append(item)
        if expanded_items:
            projection.items = expanded_items
            projection.media = expanded_media
            projection.tree = build_projection_tree(rule.projection, projection.items, projection.media)
            projection.debug_events.append(
                DebugEvent(
                    phase="detail-expand",
                    message="Expanded intermediate detail links into resource items",
                    data={"items": len(expanded_items), "media": len(expanded_media)},
                )
            )
            if expanded_media:
                projection.warnings = [warning for warning in projection.warnings if "No direct media" not in warning]
        return projection

    async def _resolve_detail_chain(self, rule: WebMediaRule, html: str, base_url: str) -> list[str]:
        selectors = [
            (rule.detail_url_selector, rule.detail_url_mode),
            (rule.detail_url_selector_2, rule.detail_url_mode_2),
            (rule.detail_url_selector_3, rule.detail_url_mode_3),
        ]
        current_pages = [(html, base_url)]
        media_urls: list[str] = []
        for selector, mode in selectors[: max(0, rule.detail_url_max_hops)]:
            if not selector:
                break
            next_urls: list[str] = []
            for page_html, page_url in current_pages:
                next_urls.extend(
                    extract_links_by_selector(
                        page_html,
                        page_url,
                        selector,
                        limit=1 if mode == "single" else self.settings.max_items,
                    )
                )
            current_pages = []
            for next_url in next_urls[: self.settings.max_items]:
                try:
                    loaded = await self.fetcher.load(next_url, force_desktop=rule.force_desktop_mode or True, fast_mode=rule.fast_mode)
                except Exception:
                    continue
                found = extract_media_urls(loaded.html, loaded.final_url, str(rule.media_type))
                media_urls.extend(found)
                if found and rule.detail_url_stop_when_media_found:
                    continue
                current_pages.append((loaded.html, loaded.final_url))
        return media_urls

    def _add_network_media(self, rule: WebMediaRule, projection: ProjectionResult, network_urls: list[str]) -> None:
        if not rule.force_network_sniff or not network_urls:
            return
        from zwmp_rule.media import is_media_url

        existing = {entry.url for entry in projection.media}
        target_item = projection.items[0] if projection.items else None
        if target_item is None:
            return
        for url in network_urls:
            if url in existing or not is_media_url(url, rule.media_type):
                continue
            media_id = f"sniffed-{len(projection.media) + 1}"
            projection.media.append(
                ProjectionMedia(
                    id=media_id,
                    item_id=target_item.id,
                    url=url,
                    type=rule.media_type,
                    extension=extension_for_url(url) or "url",
                    delivery="direct",
                )
            )
            target_item.media_ids.append(media_id)
            target_item.status = "resolved"
        projection.tree = build_projection_tree(rule.projection, projection.items, projection.media)

    def _runtime_notices(self, ai_used: bool, browser_used: bool, browser_reason: str | None, sniff_requested: bool) -> list[RuntimeNotice]:
        notices: list[RuntimeNotice] = []
        if not ai_used:
            notices.append(
                RuntimeNotice(
                    kind="ai_fallback",
                    message="AI analysis was not used; deterministic heuristics generated the rule.",
                    action="Set ZWMP_AI_PROVIDER and ZWMP_AI_API_KEY in .env, then restart with scripts/dev.sh.",
                )
            )
        if not browser_used:
            notices.append(
                RuntimeNotice(
                    kind="browser_fallback",
                    message=browser_reason or "Browser runtime was not used; plain HTTP loading was used.",
                    action="Install Playwright browsers with: cd apps/api && .venv/bin/python -m playwright install chromium.",
                )
            )
        if sniff_requested and not browser_used:
            notices.append(
                RuntimeNotice(
                    kind="sniffing_limited",
                    message="Network sniffing is limited because the browser runtime was unavailable.",
                    action="Enable Playwright browser runtime for full request sniffing and playback interaction support.",
                )
            )
        return notices

    def _register_proxy_media(self, job_id: str, projection: ProjectionResult) -> None:
        for media in projection.media:
            self.proxy_media[f"{job_id}:{media.id}"] = {"url": media.url, **media.headers_hint}

    def proxy_target(self, session_id: str, media_id: str) -> dict[str, str] | None:
        return self.proxy_media.get(f"{session_id}:{media_id}")

    def _update(self, job: JobResponse, phase: str, progress: float, message: str) -> None:
        job.phase = phase
        job.progress = progress
        job.debug_events.append(DebugEvent(phase=phase, message=message))
