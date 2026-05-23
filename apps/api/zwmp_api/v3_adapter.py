from __future__ import annotations

import argparse
import tempfile
from pathlib import Path
from typing import Any

from zwmp_rule.media import extension_for_url, is_media_url
from zwmp_rule.projection import build_projection_tree
from zwmp_rule.types import DebugEvent, MediaType, ProjectionItem, ProjectionMedia, ProjectionResult

from .config import Settings
from .schemas import RuntimeNotice, SiteProfile
from . import v3_engine as v3


COMMON_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


def generate_v3_rule(url: str, media_type: str, options: Any, settings: Settings, progress: Any | None = None) -> dict[str, Any]:
    ai_provider = (settings.ai_provider or "").strip()
    has_ai = bool(settings.ai_api_key and ai_provider and ai_provider != "none")
    args = argparse.Namespace(
        mode="generate",
        url=url,
        output=None,
        json=False,
        save_evidence=None,
        no_ai=not has_ai,
        api_key=settings.ai_api_key,
        base_url=ai_provider if has_ai else "https://api.openai.com/v1",
        model=settings.ai_model,
        no_response_format=False,
        timeout=settings.request_timeout_seconds,
        sample_items=getattr(options, "sample_items", 8),
        max_candidate_groups=getattr(options, "max_candidate_groups", 6),
        validate_hypotheses=getattr(options, "validate_hypotheses", 5),
        validation_limit=getattr(options, "validation_limit", 24),
        detail_probes=getattr(options, "detail_probes", settings.probe_items),
        scroll_steps=getattr(options, "scroll_steps", 3),
        no_click_play=True,
        max_items=getattr(options, "max_items", None) or settings.max_items,
        desktop=getattr(options, "desktop", False),
        headful=False,
        log_level="INFO",
        no_color=True,
        user_agent=COMMON_USER_AGENT,
        progress_callback=progress,
    )
    result = v3.run_generation(args)
    rule = dict(result.rule)
    rule["media_type"] = media_type or rule.get("media_type", "video")
    if getattr(options, "force_network_sniff", False):
        rule["force_network_sniff"] = True
    rendered = v3.render_rule(
        rule,
        confidence=result.confidence,
        reasoning=result.reasoning,
        detail_url_examples=result.detail_url_examples,
    )
    return {
        "rule": rule,
        "rule_text": rendered,
        "site_profile": site_profile_from_inference(result, media_type),
        "v3": v3.json_output(result),
        "runtime_notices": runtime_notices(result.used_ai),
        "alternatives": alternatives_from_inference(result),
        "warnings": warnings_from_inference(result),
    }


def generate_v3(url: str, media_type: str, options: Any, settings: Settings, progress: Any | None = None) -> dict[str, Any]:
    generated = generate_v3_rule(url, media_type, options, settings, progress)
    preview = execute_rule_preview(generated["rule_text"], settings, progress)
    generated["projection"] = preview["projection"]
    generated["warnings"] = [*generated["warnings"], *preview["projection"].warnings]
    return generated


def preview_v3(rule_text: str, settings: Settings, progress: Any | None = None) -> dict[str, Any]:
    return execute_rule_preview(rule_text, settings, progress)


def execute_rule_preview(rule_text: str, settings: Settings, progress: Any | None = None) -> dict[str, Any]:
    initial_rule = v3.parse_rule_text(rule_text, "", max_items=500)
    with tempfile.NamedTemporaryFile("w", suffix=".wm", encoding="utf-8", delete=False) as file:
        file.write(rule_text)
        path = Path(file.name)
    try:
        args = argparse.Namespace(
            mode="debug",
            command="debug",
            rule_file=str(path),
            json=True,
            limit=rule_preview_limit(initial_rule, settings),
            timeout=settings.request_timeout_seconds,
            desktop=False,
            headful=False,
            log_level="INFO",
            no_color=True,
            user_agent=COMMON_USER_AGENT,
        )
        if progress:
            progress("preview-listing", 0.08, "Loading source page and resolving rule candidates")
        items, events, diagnoses, rule = v3.debug_rule(args)
        if progress:
            progress("preview-detail-pages", 0.36, f"Inspecting {len(items)} projected item pages for media")
        probes = preview_detail_probes(items, rule, settings, progress=progress, start=0.36, end=0.88)
        if progress:
            progress("preview-building-view", 0.9, "Building resource view")
        projection = projection_from_debug(items, events, diagnoses, rule, probes)
        return {
            "projection": projection,
            "site_profile": SiteProfile(
                category=str(rule.get("media_type") or "media"),
                language="unknown",
                layout_type="v3-debug",
                content_type=str(rule.get("media_type") or "video"),
                confidence=0.0,
                notes=str(rule.get("source") or ""),
            ),
            "debug": {
                "rule": rule,
                "events": [v3.to_plain(event) for event in events],
                "diagnoses": diagnoses,
                "items": items,
                "detail_probes": [v3.to_plain(probe) for probe in probes],
            },
            "runtime_notices": [],
        }
    finally:
        path.unlink(missing_ok=True)


def rule_preview_limit(rule: dict[str, Any], settings: Settings) -> int:
    try:
        return max(1, int(rule.get("max_items") or settings.max_items))
    except (TypeError, ValueError):
        return settings.max_items


def projection_from_inference(result: Any, rule: dict[str, Any]) -> ProjectionResult:
    validation = max(result.validations, key=lambda item: item.quality_score) if result.validations else None
    items: list[ProjectionItem] = []
    media: list[ProjectionMedia] = []
    media_type = MediaType(rule.get("media_type", "video"))
    if validation:
        for index, sample in enumerate(validation.listing.sample_items[: int(rule.get("max_items", 50))], start=1):
            item_id = f"item-{index}"
            title = sample.get("title") or sample.get("href") or f"Item {index}"
            detail_url = sample.get("href", "")
            item = ProjectionItem(
                id=item_id,
                title=title,
                detail_url=detail_url,
                thumbnail_url=sample.get("thumbnail") or None,
                duration=sample.get("duration") or None,
                status="pending",
            )
            if is_media_url(detail_url, media_type):
                media_id = f"media-{len(media) + 1}"
                media.append(
                    ProjectionMedia(
                        id=media_id,
                        item_id=item_id,
                        url=detail_url,
                        type=media_type,
                        extension=extension_for_url(detail_url) or "url",
                        delivery="direct",
                    )
                )
                item.media_ids.append(media_id)
                item.status = "resolved"
            items.append(item)
    for probe_index, probe in enumerate(validation.detail_probes if validation else [], start=1):
        item = items[min(probe_index - 1, len(items) - 1)] if items else None
        if item is None:
            item = ProjectionItem(id=f"item-{probe_index}", title=probe.item_title or f"Item {probe_index}", detail_url=probe.final_url or probe.item_url)
            items.append(item)
        for row in primary_media_rows_for_rule(probe, str(media_type)):
            url = str(row.get("url") or row.get("src") or "")
            if not url:
                continue
            if any(existing.item_id == item.id and existing.url == url for existing in media):
                continue
            media_id = f"media-{len(media) + 1}"
            media.append(
                ProjectionMedia(
                    id=media_id,
                    item_id=item.id,
                    url=url,
                    type=media_type,
                    extension=extension_for_url(url) or "url",
                    delivery="direct",
                )
            )
            item.media_ids.append(media_id)
            item.status = "resolved"
        if item.status != "resolved":
            item.status = "needs-interaction"
            item.warning = "No primary media was discovered during v3 detail probing."
    warnings = warnings_from_inference(result)
    debug_events = [
        DebugEvent(
            phase="v3-validation",
            message=f"Validated {len(result.validations)} hypotheses with v3 browser-first engine",
            data={"confidence": result.confidence, "used_ai": result.used_ai},
        )
    ]
    return ProjectionResult(
        tree=build_projection_tree(rule.get("projection", "by-item"), items, media),
        items=items,
        media=media,
        debug_events=debug_events,
        warnings=warnings,
    )


def projection_from_debug(
    items_raw: list[dict[str, str]],
    events: list[Any],
    diagnoses: list[str],
    rule: dict[str, Any],
    probes: list[Any] | None = None,
) -> ProjectionResult:
    items: list[ProjectionItem] = []
    media: list[ProjectionMedia] = []
    media_type = MediaType(rule.get("media_type", "video"))
    for index, row in enumerate(items_raw, start=1):
        item_id = f"item-{index}"
        url = row.get("url", "")
        item = ProjectionItem(id=item_id, title=row.get("title") or url or f"Item {index}", detail_url=url, status="pending")
        if is_media_url(url, media_type):
            media_id = f"media-{index}"
            media.append(
                ProjectionMedia(
                    id=media_id,
                    item_id=item_id,
                    url=url,
                    type=media_type,
                    extension=extension_for_url(url) or "url",
                    delivery="direct",
                )
            )
            item.media_ids.append(media_id)
            item.status = "resolved"
        items.append(item)
    item_by_url = {item.detail_url: item for item in items if item.detail_url}
    for probe in probes or []:
        item = item_by_url.get(probe.item_url) or item_by_url.get(probe.final_url)
        if item is None:
            item = ProjectionItem(
                id=f"item-{len(items) + 1}",
                title=probe.item_title or probe.item_url or f"Item {len(items) + 1}",
                detail_url=probe.final_url or probe.item_url,
                status="pending",
            )
            items.append(item)
            if item.detail_url:
                item_by_url[item.detail_url] = item
        for row in primary_media_rows_for_rule(probe, str(media_type)):
            url = str(row.get("url") or row.get("src") or "")
            if not url or any(existing.item_id == item.id and existing.url == url for existing in media):
                continue
            media_id = f"media-{len(media) + 1}"
            media.append(
                ProjectionMedia(
                    id=media_id,
                    item_id=item.id,
                    url=url,
                    type=media_type,
                    extension=extension_for_url(url) or "url",
                    delivery="direct",
                )
            )
            item.media_ids.append(media_id)
            item.status = "resolved"
        if item.status != "resolved" and probe.status == "ok":
            item.status = "needs-interaction"
            item.warning = "No primary media was discovered during v3 detail probing."
    return ProjectionResult(
        tree=build_projection_tree(rule.get("projection", "by-item"), items, media),
        items=items,
        media=media,
        debug_events=[
            DebugEvent(
                phase=getattr(event, "kind", "debug"),
                message=getattr(event, "message", ""),
                level="info" if getattr(event, "level", "info") == "success" else getattr(event, "level", "info"),
                data=getattr(event, "data", {}),
            )
            for event in events
        ],
        warnings=diagnoses,
    )


def preview_detail_probes(
    items: list[dict[str, str]],
    rule: dict[str, Any],
    settings: Settings,
    progress: Any | None = None,
    start: float = 0.0,
    end: float = 1.0,
) -> list[Any]:
    if not items:
        return []
    media_type = MediaType(v3.normalize_media_type(rule.get("media_type")))
    runtime = v3.BrowserRuntime(v3.configured_proxy_url(), headless=True)
    try:
        probe_items = [item for item in items if item.get("url") and not is_media_url(item.get("url", ""), media_type)]
        probes = []
        total = max(1, len(probe_items))
        for index, item in enumerate(probe_items, start=1):
            if progress:
                progress(
                    "preview-detail-pages",
                    start + (end - start) * ((index - 1) / total),
                    f"Inspecting media for item {index} of {len(probe_items)}",
                )
            probes.append(
                v3.probe_detail_page(
                    runtime,
                    {"href": item.get("url", ""), "title": item.get("title", "")},
                    rule,
                    user_agent=COMMON_USER_AGENT,
                    timeout=settings.request_timeout_seconds,
                    click_play=False,
                    desktop=bool(rule.get("force_desktop_mode")),
                )
            )
        return probes
    finally:
        runtime.close()


def primary_media_rows_for_rule(probe: Any, media_type: str) -> list[dict[str, Any]]:
    rows = v3.probe_primary_media_rows(probe, media_type)
    if rows:
        return rows
    return [
        row
        for row in [*probe.dom_media, *probe.network_media_after_load, *probe.network_media_after_click]
        if v3.media_type_matches(str(row.get("url") or row.get("src") or ""), media_type)
    ]


def site_profile_from_inference(result: Any, media_type: str) -> SiteProfile:
    intent = result.hypotheses[0].page_intent if result.hypotheses else "media"
    return SiteProfile(
        category=str(intent or "media"),
        language="unknown",
        layout_type="browser-evidence",
        content_type=media_type,
        confidence=safe_confidence(result.confidence),
        notes=result.evidence.title,
    )


def safe_confidence(value: str) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def alternatives_from_inference(result: Any) -> list[dict[str, Any]]:
    out = []
    validations = {validation.hypothesis_id: validation for validation in result.validations}
    for hypothesis in result.hypotheses:
        validation = validations.get(hypothesis.id)
        out.append(
            {
                "rule_text": v3.render_rule(hypothesis.rule_draft),
                "score": validation.quality_score if validation else hypothesis.confidence,
                "reason": f"{hypothesis.id} {hypothesis.source}: {hypothesis.page_intent}",
            }
        )
    return out


def warnings_from_inference(result: Any) -> list[str]:
    warnings: list[str] = []
    for validation in result.validations:
        warnings.extend(validation.warnings)
    for hypothesis in result.hypotheses:
        warnings.extend(hypothesis.risks)
    return list(dict.fromkeys(warnings))[:12]


def runtime_notices(used_ai: bool) -> list[RuntimeNotice]:
    if used_ai:
        return []
    return [
        RuntimeNotice(
            kind="ai_fallback",
            message="AI finalization was not used; v3 local validation selected the rule.",
            action="Set ZWMP_AI_PROVIDER, ZWMP_AI_API_KEY, and ZWMP_AI_MODEL in .env to enable v3 AI hypotheses/finalization.",
        )
    ]
