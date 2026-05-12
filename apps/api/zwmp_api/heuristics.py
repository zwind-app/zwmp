from __future__ import annotations

import html
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from zwmp_rule import extract_media_urls, format_rule
from zwmp_rule.media import extension_for_url
from zwmp_rule.types import DebugEvent, ProjectionItem, ProjectionMedia, ProjectionResult, WebMediaRule

from .schemas import RuleDraft, SiteProfile


GENERIC_CLASSES = {
    "active",
    "box",
    "card",
    "clearfix",
    "col",
    "container",
    "content",
    "current",
    "flex",
    "grid",
    "hidden",
    "item",
    "lazy",
    "left",
    "link",
    "list",
    "media",
    "nav",
    "right",
    "row",
    "selected",
    "show",
    "thumb",
    "thumbnail",
    "title",
    "video",
    "visible",
    "wrapper",
}


@dataclass
class AnchorCandidate:
    href: str
    absolute_url: str
    text: str = ""
    classes: list[str] = field(default_factory=list)
    image_count: int = 0
    image_sources: list[str] = field(default_factory=list)
    image_alts: list[str] = field(default_factory=list)


class AnchorExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.anchors: list[AnchorCandidate] = []
        self._current: AnchorCandidate | None = None
        self._anchor_depth = 0
        self._title_parts: list[str] = []
        self._in_title = False

    @property
    def page_title(self) -> str | None:
        title = normalize_text(" ".join(self._title_parts))
        return title or None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {name.lower(): value or "" for name, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "a":
            href = attr_map.get("href", "")
            if href and self._current is None:
                self._current = AnchorCandidate(
                    href=href,
                    absolute_url=urljoin(self.base_url, href),
                    classes=split_classes(attr_map.get("class", "")),
                )
                self._anchor_depth = 1
            elif self._current is not None:
                self._anchor_depth += 1
            return
        if self._current is not None and tag == "img":
            self._current.image_count += 1
            src = attr_map.get("src") or attr_map.get("data-src") or attr_map.get("data-original")
            alt = attr_map.get("alt")
            if src:
                self._current.image_sources.append(urljoin(self.base_url, src))
            if alt:
                self._current.image_alts.append(normalize_text(alt))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
            return
        if tag == "a" and self._current is not None:
            self._anchor_depth -= 1
            if self._anchor_depth <= 0:
                self._current.text = normalize_text(self._current.text)
                self.anchors.append(self._current)
                self._current = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        if self._current is not None:
            self._current.text += " " + data


def analyze_site(html_text: str, url: str, media_type: str) -> tuple[SiteProfile, list[RuleDraft], list[DebugEvent]]:
    extractor = AnchorExtractor(url)
    extractor.feed(html_text)
    anchors = dedupe_anchors([a for a in extractor.anchors if is_plausible_detail_url(a.absolute_url)])
    image_anchors = [a for a in anchors if a.image_count > 0]
    class_counts: Counter[str] = Counter()
    for anchor in anchors:
        class_counts.update(c for c in anchor.classes if c not in GENERIC_CLASSES)
    card_classes = infer_card_classes(html_text)
    href_shapes = Counter(url_shape(anchor.absolute_url) for anchor in anchors)
    category = infer_category(url, extractor.page_title, media_type)

    drafts: list[RuleDraft] = []
    selectors: list[tuple[str, str]] = []
    if card_classes:
        selectors.append((f".{card_classes[0][0]}", "repeated card class"))
    if class_counts:
        selectors.append((f"a.{class_counts.most_common(1)[0][0]}", "common anchor class"))
    if image_anchors:
        selectors.append(("a:has(img)", "image anchors"))
    selectors.append(("a[href]", "anchor fallback"))

    seen: set[str] = set()
    for selector, reason in selectors:
        if selector in seen:
            continue
        seen.add(selector)
        score = score_selector(selector, anchors, image_anchors, href_shapes)
        rule = WebMediaRule(
            source=url,
            candidate_selector=selector,
            projection="by-item",
            media_type=media_type,
            max_items=min(30, max(1, len(anchors))),
        )
        drafts.append(RuleDraft(rule_text=format_rule(rule), score=score, reason=reason))

    drafts.sort(key=lambda draft: draft.score, reverse=True)
    events = [
        DebugEvent(
            phase="list-discovery",
            message="Analyzed page anchors and repeated structures",
            data={
                "anchors": len(anchors),
                "image_anchors": len(image_anchors),
                "common_anchor_classes": class_counts.most_common(8),
                "common_card_classes": card_classes[:8],
                "href_shapes": href_shapes.most_common(8),
            },
        )
    ]
    profile = SiteProfile(
        category=category,
        language=infer_language(extractor.page_title or html_text[:500]),
        layout_type="list/grid" if image_anchors else "link-list",
        content_type=media_type,
        confidence=0.65 if anchors else 0.2,
        notes=extractor.page_title,
    )
    return profile, drafts, events


def build_projection_from_rule(rule: WebMediaRule, html_text: str, final_url: str) -> ProjectionResult:
    extractor = AnchorExtractor(final_url)
    extractor.feed(html_text)
    anchors = dedupe_anchors([a for a in extractor.anchors if is_plausible_detail_url(a.absolute_url)])
    if "img" in rule.candidate_selector:
        anchors = [a for a in anchors if a.image_count > 0] or anchors
    if rule.max_items:
        anchors = anchors[: rule.max_items]
    media_urls = extract_media_urls(html_text, final_url, str(rule.media_type))

    items: list[ProjectionItem] = []
    media: list[ProjectionMedia] = []
    for index, anchor in enumerate(anchors, start=1):
        item_id = f"item-{index}"
        title = anchor.text or next((alt for alt in anchor.image_alts if alt), "") or title_from_url(anchor.absolute_url)
        item = ProjectionItem(
            id=item_id,
            title=title,
            detail_url=anchor.absolute_url,
            thumbnail_url=anchor.image_sources[0] if anchor.image_sources else None,
            status="pending",
        )
        items.append(item)
    if media_urls:
        if not items:
            items.append(ProjectionItem(id="item-1", title=extractor.page_title or title_from_url(final_url), detail_url=final_url, status="resolved"))
        for index, media_url in enumerate(media_urls, start=1):
            item = items[min(index - 1, len(items) - 1)]
            media_id = f"media-{index}"
            extension = extension_for_url(media_url) or "url"
            media.append(
                ProjectionMedia(
                    id=media_id,
                    item_id=item.id,
                    url=media_url,
                    type=rule.media_type,
                    extension=extension,
                    delivery="direct",
                    requires_proxy=False,
                )
            )
            item.media_ids.append(media_id)
            item.status = "resolved"
    warnings = []
    if items and not media:
        warnings.append("No direct media URL was found on the listing page. Candidate detail probing may be required.")
        for item in items[:3]:
            item.status = "needs-interaction"
            item.warning = "Media may live on the detail page or require playback sniffing."
    if not items:
        warnings.append("No candidate items were found.")
    from zwmp_rule import build_projection_tree

    return ProjectionResult(
        tree=build_projection_tree(rule.projection, items, media),
        items=items,
        media=media,
        warnings=warnings,
        debug_events=[
            DebugEvent(
                phase="projection",
                message="Built projection preview from loaded page",
                data={"items": len(items), "media": len(media), "final_url": final_url},
            )
        ],
    )


def extract_links_by_selector(html_text: str, base_url: str, selector: str | None, limit: int = 50) -> list[str]:
    extractor = AnchorExtractor(base_url)
    extractor.feed(html_text)
    anchors = extractor.anchors
    if not selector:
        return [anchor.absolute_url for anchor in anchors[:limit]]
    matched = [anchor.absolute_url for anchor in anchors if anchor_matches_selector(anchor, selector)]
    return matched[:limit]


def anchor_matches_selector(anchor: AnchorCandidate, selector: str) -> bool:
    selector = selector.strip()
    if selector in {"a", "a[href]"}:
        return True
    class_match = re.fullmatch(r"a?\.([A-Za-z_][A-Za-z0-9_-]*)", selector)
    if class_match:
        return class_match.group(1) in anchor.classes
    href_contains = re.search(r"href\*=[\"']([^\"']+)[\"']", selector)
    if href_contains:
        return href_contains.group(1) in anchor.href or href_contains.group(1) in anchor.absolute_url
    if selector.startswith("."):
        wanted = selector[1:].split()[0]
        return wanted in anchor.classes
    return False


def choose_best_draft(drafts: list[RuleDraft], projection: ProjectionResult | None = None) -> RuleDraft:
    if not projection:
        return drafts[0]
    media_bonus = 0.2 if projection.media else 0.0
    adjusted = drafts[0].model_copy(update={"score": drafts[0].score + media_bonus})
    return adjusted


def split_classes(value: str) -> list[str]:
    return [part for part in re.split(r"\s+", value.strip()) if re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", part)]


def normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def dedupe_anchors(anchors: list[AnchorCandidate]) -> list[AnchorCandidate]:
    seen: set[str] = set()
    result: list[AnchorCandidate] = []
    for anchor in anchors:
        if anchor.absolute_url in seen:
            continue
        seen.add(anchor.absolute_url)
        result.append(anchor)
    return result


def is_plausible_detail_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered = parsed.path.lower()
    if any(lowered.endswith(ext) for ext in (".css", ".js", ".ico", ".xml", ".json")):
        return False
    return True


def infer_card_classes(html_text: str) -> list[tuple[str, int]]:
    counts = Counter()
    for class_attr in re.findall(r"\bclass=[\"']([^\"']+)[\"']", html_text, re.I):
        classes = split_classes(class_attr)
        if any(name in GENERIC_CLASSES for name in classes):
            for class_name in classes:
                if class_name not in GENERIC_CLASSES:
                    counts[class_name] += 1
    return counts.most_common(12)


def url_shape(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    shaped = [re.sub(r"\d+", "{n}", part) for part in parts[:4]]
    return "/" + "/".join(shaped)


def score_selector(selector: str, anchors: list[AnchorCandidate], image_anchors: list[AnchorCandidate], href_shapes: Counter[str]) -> float:
    if not anchors:
        return 0.0
    score = 0.2
    if selector == "a:has(img)":
        score += min(0.45, len(image_anchors) / max(1, len(anchors)))
    if selector.startswith("a."):
        score += 0.3
    if selector.startswith("."):
        score += 0.35
    if href_shapes:
        score += min(0.2, href_shapes.most_common(1)[0][1] / len(anchors))
    return round(min(score, 0.95), 3)


def infer_category(url: str, title: str | None, media_type: str) -> str:
    text = f"{url} {title or ''}".lower()
    if media_type == "image":
        return "gallery"
    if media_type == "audio":
        return "audio"
    if any(token in text for token in ("episode", "season", "drama", "series", "anime", "tv")):
        return "series"
    if any(token in text for token in ("video", "movie", "watch", "play")):
        return "streaming"
    if any(token in text for token in ("feed", "post", "blog")):
        return "feed"
    return "media"


def infer_language(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "unknown" if not text.strip() else "en"


def title_from_url(url: str) -> str:
    parsed = urlparse(url)
    tail = [part for part in parsed.path.split("/") if part]
    if not tail:
        return parsed.hostname or "item"
    return re.sub(r"[-_]+", " ", tail[-1].rsplit(".", 1)[0]).strip() or "item"
