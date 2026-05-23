#!/usr/bin/env python3
"""
web_media_rule_generator_v3_fixed.py

A browser-first Web Media Projection Resolver rule generator, v3 fixed.

This version follows the same workflow a human usually uses in DevTools:

1. Render the listing page and visually locate repeated video/media cards.
2. Inspect one card to infer the container, detail link, title, thumbnail, duration.
3. Open sample detail/intermediate pages.
4. Decide whether the sample page is an intermediate page or a playable detail page.
5. Inspect player DOM, <video>/<source>/<audio>, iframe, episode/play links.
6. Watch network before and after clicking a likely play button.
7. Generate and validate .wm rule candidates; optionally ask an OpenAI-compatible
   chat API to choose or repair the final rule from verified evidence.

Examples:
  OPENAI_API_KEY=sk-... python3 web_media_rule_generator_v3.py https://example.com/videos

  OPENAI_API_KEY=... \
  OPENAI_BASE_URL=https://api.deepseek.com/v1 \
  OPENAI_MODEL=deepseek-chat \
  python3 web_media_rule_generator_v3.py https://example.com/videos --output top.wm

  python3 web_media_rule_generator_v3.py https://example.com/videos --no-ai --json

  python3 web_media_rule_generator_v3.py debug -r top.wm --json
"""

from __future__ import annotations

import argparse
import dataclasses
import html
import json
import logging
import os
import re
import shutil
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


LOGGER = logging.getLogger("web_media_rule_generator_v3")
_COLOR_ENABLED = False


SUPPORTED_RULE_KEYS = (
    "source",
    "candidate_selector",
    "candidate_link_selector",
    "detail_url_selector",
    "detail_url_mode",
    "detail_url_selector_2",
    "detail_url_mode_2",
    "detail_url_selector_3",
    "detail_url_mode_3",
    "detail_url_max_hops",
    "detail_url_stop_when_media_found",
    "max_detail_concurrency",
    "title_selector",
    "thumbnail_selector",
    "duration_selector",
    "media_type",
    "media_url_ttl",
    "media_delivery",
    "projection",
    "max_items",
    "force_network_sniff",
    "fast_mode",
    "force_desktop_mode",
    "selector_wait_timeout",
    "network_sniff_timeout",
    "network_sniff_idle_timeout",
)

GENERIC_CLASSES = {
    "active", "box", "card", "clearfix", "col", "container", "content", "current",
    "flex", "grid", "hidden", "item", "lazy", "left", "link", "list", "media",
    "nav", "right", "row", "selected", "show", "thumb", "thumbnail", "title",
    "video", "visible", "wrapper", "swiper-slide", "slick-slide",
}

RANDOM_CLASS_RE = re.compile(
    r"(^[a-zA-Z0-9_-]{12,}$|css-[a-z0-9]+|_[a-z0-9]{6,}|__[a-z0-9]{6,}|"
    r"^svelte-|^astro-|^ng-|^v-[a-f0-9]+$)",
    re.I,
)

VIDEO_EXTS = {"m3u8", "mpd", "mp4", "webm", "mov", "m4v", "m4s", "ts"}
AUDIO_EXTS = {"mp3", "m4a", "aac", "flac", "ogg", "opus", "wav"}
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "avif", "svg", "bmp", "heic", "heif"}

MEDIA_URL_RE = re.compile(
    r"""(?ix)
    (?:
      https?:\\?/\\?/|//
    )
    [^\s"'<>]+?
    \.
    (?:m3u8|mpd|mp4|webm|mov|m4v|m4s|ts|mp3|m4a|aac|flac|ogg|opus|wav|jpe?g|png|gif|webp|avif|svg|bmp|heic|heif)
    (?:\?[^\s"'<>]*)?
    """
)

# v3: these fields are currently not supported by the resolver/app layer.
# Keep the switch explicit so it is easy to re-enable later without touching prompts.
ENABLE_PLAYER_SELECTOR_FIELDS = False
ENABLE_CLICK_PLAY_PROBE = False


class Ansi:
    reset = "\033[0m"
    bold = "\033[1m"
    dim = "\033[2m"
    red = "\033[31m"
    green = "\033[32m"
    yellow = "\033[33m"
    blue = "\033[34m"
    magenta = "\033[35m"
    cyan = "\033[36m"


def enable_color(enabled: bool) -> None:
    global _COLOR_ENABLED
    _COLOR_ENABLED = enabled


def colorize(text: str, *styles: str) -> str:
    if not _COLOR_ENABLED or not styles:
        return text
    return "".join(styles) + text + Ansi.reset


def configure_logging(level: str) -> None:
    numeric = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=numeric,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


@dataclass
class LinkEvidence:
    href: str
    abs_url: str
    text: str = ""
    selector: str = ""
    has_image: bool = False
    classes: list[str] = field(default_factory=list)
    href_shape: str = ""


@dataclass
class ImageEvidence:
    src: str
    abs_url: str
    alt: str = ""
    selector: str = ""
    width: int = 0
    height: int = 0
    role: str = "unknown"


@dataclass
class TextEvidence:
    text: str
    selector: str = ""
    score: float = 0.0


@dataclass
class CardSample:
    index: int
    text: str
    html_excerpt: str
    bbox: dict[str, float]
    links: list[LinkEvidence] = field(default_factory=list)
    images: list[ImageEvidence] = field(default_factory=list)
    title_candidates: list[TextEvidence] = field(default_factory=list)
    duration_candidates: list[TextEvidence] = field(default_factory=list)


@dataclass
class CandidateGroup:
    group_id: str
    selector: str
    tag: str
    count: int
    visible_count: int
    layout: str
    page_region: str
    score: float
    score_breakdown: dict[str, float]
    link_selector_hints: list[tuple[str, int]]
    title_selector_hints: list[tuple[str, int]]
    thumbnail_selector_hints: list[tuple[str, int]]
    duration_selector_hints: list[tuple[str, int]]
    href_shapes: list[tuple[str, int]]
    samples: list[CardSample]
    negative_signals: list[str] = field(default_factory=list)


@dataclass
class PageEvidence:
    requested_url: str
    final_url: str
    title: str | None
    viewport: dict[str, int]
    candidate_groups: list[CandidateGroup]
    network_media_after_load: list[dict[str, Any]]
    resource_summary: dict[str, int]
    lazy_load_observed: bool
    html_skeleton: str
    collected_at: str


@dataclass
class DetailProbe:
    item_title: str
    item_url: str
    final_url: str = ""
    status: str = "ok"
    page_kind: str = "unknown"  # intermediate | playable_detail | gallery | unknown
    title: str | None = None
    title_match_score: float = 0.0
    title_in_page_title: bool = False
    dom_media: list[dict[str, Any]] = field(default_factory=list)
    network_media_after_load: list[dict[str, Any]] = field(default_factory=list)
    network_media_after_click: list[dict[str, Any]] = field(default_factory=list)
    player_candidates: list[dict[str, Any]] = field(default_factory=list)
    play_button_candidates: list[dict[str, Any]] = field(default_factory=list)
    clicked_play_selector: str | None = None
    episode_links: list[LinkEvidence] = field(default_factory=list)
    play_links: list[LinkEvidence] = field(default_factory=list)
    iframe_candidates: list[dict[str, Any]] = field(default_factory=list)
    suggested_detail_selector: str | None = None
    suggested_detail_mode: str = "single"
    error: str | None = None


@dataclass
class RuleHypothesis:
    id: str
    source: str
    page_intent: str
    rule_draft: dict[str, Any]
    expected_chain: list[str]
    needs_probe: list[str]
    confidence: float
    risks: list[str] = field(default_factory=list)


@dataclass
class ListingValidation:
    candidate_count: int
    visible_candidate_count: int
    link_coverage: float
    title_coverage: float
    thumbnail_coverage: float
    duration_coverage: float
    href_shapes: list[tuple[str, int]]
    sample_items: list[dict[str, str]]
    errors: list[str] = field(default_factory=list)


@dataclass
class HypothesisValidation:
    hypothesis_id: str
    listing: ListingValidation
    detail_probes: list[DetailProbe]
    quality_score: float
    suggested_repairs: dict[str, Any]
    warnings: list[str] = field(default_factory=list)


@dataclass
class InferenceResult:
    rule: dict[str, Any]
    used_ai: bool
    confidence: str
    reasoning: str
    detail_url_examples: list[str]
    evidence: PageEvidence
    hypotheses: list[RuleHypothesis]
    validations: list[HypothesisValidation]


@dataclass
class DebugEvent:
    kind: str
    message: str
    level: str = "info"
    data: dict[str, Any] = field(default_factory=dict)


def now_string() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def one_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def normalized_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def title_tokens(value: str) -> set[str]:
    value = normalized_text(value).lower()
    # Drop common site-name suffixes in <title>, e.g. "Video name - Site".
    value = re.split(r"\s[-_|·—]+\s", value, maxsplit=1)[0] if value else value
    tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", value))
    return {token for token in tokens if token not in {"video", "videos", "watch", "play", "home", "page"}}


def title_match_score(item_title: str, page_title: str | None) -> float:
    item = normalized_text(item_title)
    page = normalized_text(page_title or "")
    if not item or not page:
        return 0.0
    item_lower = item.lower()
    page_lower = page.lower()
    if item_lower and item_lower in page_lower:
        return 1.0
    item_tok = title_tokens(item)
    page_tok = title_tokens(page)
    if not item_tok or not page_tok:
        return 0.0
    overlap = len(item_tok & page_tok) / max(1, len(item_tok))
    return round(clamp(overlap, 0.0, 1.0), 3)


def is_safe_css_class(value: str) -> bool:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_-]*$", value or ""):
        return False
    if value in GENERIC_CLASSES:
        return False
    if RANDOM_CLASS_RE.search(value):
        return False
    return True


def normalize_raw_url(value: str) -> str:
    value = (value or "").strip().strip("\"'")
    value = html.unescape(value).replace("\\/", "/").strip().strip("\"'")
    return re.split(r"[\"'<>\s]", value, maxsplit=1)[0] if value else ""


def normalize_url(raw_url: str, base_url: str) -> str:
    value = normalize_raw_url(raw_url)
    if not value:
        return ""
    if value.startswith("//"):
        parsed = urllib.parse.urlparse(base_url)
        return f"{parsed.scheme or 'https'}:{value}"
    return urllib.parse.urljoin(base_url, value)


def strip_tracking_query(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    kept = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if not key.lower().startswith(("utm_", "spm", "fbclid", "gclid")):
            kept.append((key, value))
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(kept), fragment=""))


def url_shape(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    parts: list[str] = []
    for part in parsed.path.strip("/").split("/"):
        if not part:
            continue
        if re.fullmatch(r"\d+", part):
            parts.append("{num}")
        elif re.fullmatch(r"[0-9a-fA-F]{8,}", part):
            parts.append("{hex}")
        elif re.search(r"\d", part):
            parts.append(re.sub(r"\d+", "{num}", part))
        else:
            parts.append(part)
    shape = "/" + "/".join(parts)
    if parsed.query:
        query_keys = sorted(k for k, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))[:4]
        if query_keys:
            shape += "?" + "&".join(f"{key}=..." for key in query_keys)
    return shape


def media_kind_from_url(value: str) -> str:
    raw = normalize_raw_url(value).lower()
    if raw.startswith(("data:", "blob:", "javascript:")):
        return "unknown"
    path = raw.split("?", 1)[0].split("#", 1)[0]
    match = re.search(r"\.([a-z0-9]+)$", path)
    ext = match.group(1) if match else ""
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    if ext in IMAGE_EXTS:
        return "image"
    return "unknown"


def media_type_matches(value: str, media_type: str) -> bool:
    kind = media_kind_from_url(value)
    media_type = normalize_media_type(media_type)
    return kind != "unknown" if media_type == "all" else kind == media_type


def normalize_media_type(value: Any) -> str:
    raw = str(value or "video").strip().lower()
    aliases = {
        "videos": "video", "movie": "video", "movies": "video", "hls": "video", "dash": "video",
        "audios": "audio", "music": "audio", "podcast": "audio",
        "images": "image", "photo": "image", "photos": "image", "gallery": "image",
        "any": "all", "media": "all",
    }
    raw = aliases.get(raw, raw)
    return raw if raw in {"video", "audio", "image", "all"} else "video"


def is_plausible_detail_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered = url.lower()
    blocked = (
        "/login", "/logout", "/register", "/signup", "/search", "/tag/",
        "/category/", "/page/", "/privacy", "/terms", "javascript:", "mailto:",
    )
    return not any(token in lowered for token in blocked)


def configured_proxy_url() -> str | None:
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.getenv(key, "").strip()
        if value:
            return value
    return None


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(value, hi))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class BrowserRuntime:
    def __init__(self, proxy_url: str | None, headless: bool = True) -> None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("playwright is required for v3 browser-first analysis") from exc

        self._sync_playwright = sync_playwright
        self._playwright = sync_playwright().start()
        launch_kwargs: dict[str, Any] = {"headless": headless}
        if proxy_url:
            launch_kwargs["proxy"] = {"server": proxy_url}
        self.browser = self._playwright.chromium.launch(**launch_kwargs)

    def close(self) -> None:
        self.browser.close()
        self._playwright.stop()

    def new_context(self, user_agent: str, desktop: bool = False):
        viewport = {"width": 1440, "height": 1000} if desktop else {"width": 390, "height": 844}
        return self.browser.new_context(
            user_agent=user_agent,
            ignore_https_errors=True,
            viewport=viewport,
            is_mobile=not desktop,
            has_touch=not desktop,
        )


def collect_network_media(page, sink: list[dict[str, Any]], base_url: str) -> None:
    def on_response(response) -> None:
        try:
            url = response.url
            headers = response.headers
            content_type = (headers.get("content-type") or headers.get("Content-Type") or "").lower()
            kind = media_kind_from_url(url)
            if kind == "unknown":
                if "application/vnd.apple.mpegurl" in content_type or "mpegurl" in content_type:
                    kind = "video"
                elif content_type.startswith("video/"):
                    kind = "video"
                elif content_type.startswith("audio/"):
                    kind = "audio"
                elif content_type.startswith("image/"):
                    kind = "image"
            if kind == "unknown":
                return
            sink.append({
                "url": normalize_url(url, base_url),
                "kind": kind,
                "status": response.status,
                "content_type": content_type,
                "source": "network",
            })
        except Exception:  # noqa: BLE001
            return

    page.on("response", on_response)


def auto_scroll(page, steps: int, delay_ms: int) -> None:
    previous_height = 0
    for _ in range(max(0, steps)):
        try:
            height = page.evaluate("() => document.documentElement.scrollHeight || document.body.scrollHeight || 0")
            page.evaluate("(h) => window.scrollTo(0, h)", height)
            page.wait_for_timeout(delay_ms)
            if height == previous_height:
                break
            previous_height = height
        except Exception:  # noqa: BLE001
            break
    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:  # noqa: BLE001
        pass


LISTING_EVIDENCE_JS = r"""
({ maxGroups, maxSamples }) => {
  const genericClasses = new Set([
    "active","box","card","clearfix","col","container","content","current","flex",
    "grid","hidden","item","lazy","left","link","list","media","nav","right","row",
    "selected","show","thumb","thumbnail","title","video","visible","wrapper",
    "swiper-slide","slick-slide"
  ]);
  const randomClassRe = /(^[a-zA-Z0-9_-]{12,}$|css-[a-z0-9]+|_[a-z0-9]{6,}|__[a-z0-9]{6,}|^svelte-|^astro-|^ng-|^v-[a-f0-9]+$)/i;

  const cssEscape = (value) => {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  };

  const normText = (value) => String(value || "").replace(/\s+/g, " ").trim();

  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 20 && r.height >= 20 && r.bottom >= 0 && r.right >= 0;
  };

  const bbox = (el) => {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) };
  };

  const pageRegion = (el) => {
    const region = el.closest("header, nav, footer, aside, main, article, section");
    if (!region) return "body";
    return region.tagName.toLowerCase();
  };

  const classList = (el) => Array.from(el.classList || []).filter(Boolean);
  const stableClasses = (el) => classList(el).filter(c => !genericClasses.has(c) && !randomClassRe.test(c)).slice(0, 3);

  const selectorFor = (el) => {
    if (!el || !el.tagName) return "";
    const tag = el.tagName.toLowerCase();
    const id = el.id && !randomClassRe.test(el.id) ? `#${cssEscape(el.id)}` : "";
    if (id && document.querySelectorAll(id).length === 1) return id;
    const good = stableClasses(el);
    if (good.length) {
      const selector = `${tag}.${good.map(cssEscape).join(".")}`;
      if (document.querySelectorAll(selector).length >= 1) return selector;
      const classOnly = `.${cssEscape(good[0])}`;
      if (document.querySelectorAll(classOnly).length >= 1) return classOnly;
    }
    const classes = classList(el).filter(c => !randomClassRe.test(c)).slice(0, 2);
    if (classes.length) return `${tag}.${classes.map(cssEscape).join(".")}`;
    return tag;
  };

  const scopeRootCandidates = (el) => {
    if (!el || !el.tagName) return [];
    const tag = el.tagName.toLowerCase();
    const out = [];
    const push = (sel, weight) => {
      if (sel && !out.some(row => row.sel === sel)) out.push({ sel, weight });
    };
    if (el.id && !randomClassRe.test(el.id)) push(`#${cssEscape(el.id)}`, 100);
    const classes = classList(el).filter(c => !randomClassRe.test(c));
    const preferred = classes.filter(c => /(list|content|container|grid|items?|videos?|vod|movie|post|result|gallery|album|main|wrap)/i.test(c));
    for (const c of preferred) {
      push(`.${cssEscape(c)}`, 80);
      push(`${tag}.${cssEscape(c)}`, 75);
    }
    for (const c of classes) {
      if (genericClasses.has(c)) continue;
      push(`.${cssEscape(c)}`, 55);
      push(`${tag}.${cssEscape(c)}`, 50);
    }
    return out.sort((a, b) => b.weight - a.weight).map(row => row.sel);
  };

  const cardishRatio = (nodes) => {
    if (!nodes.length) return 0;
    let good = 0;
    for (const node of nodes) {
      const links = node.matches("a") ? [node] : Array.from(node.querySelectorAll("a[href],a[data-href],a[data-url],a[data-play-url]"));
      const imgs = Array.from(node.querySelectorAll("img, picture, [style*='background-image']"));
      const text = normText(node.innerText || node.textContent || "");
      if (isVisible(node) && links.length >= 1 && imgs.length >= 1 && text.length >= 2) good++;
    }
    return good / nodes.length;
  };

  const scopedCandidateSelector = (el) => {
    if (!el || !el.tagName) return selectorFor(el);
    const tag = el.tagName.toLowerCase();
    const simple = selectorFor(el);
    let parent = el.parentElement;
    let depth = 0;
    const candidates = [];
    while (parent && parent !== document.body && parent !== document.documentElement && depth++ < 7) {
      if (!parent.closest("header,nav,footer")) {
        for (const root of scopeRootCandidates(parent)) {
          candidates.push(`${root} ${tag}`);
          // Direct-child form is useful for validation, but keep descendant selectors first because they
          // are closer to the desired #container li / .list-content li style.
          candidates.push(`${root} > ${tag}`);
          if (simple && simple !== tag && !simple.startsWith("#")) candidates.push(`${root} ${simple}`);
        }
      }
      parent = parent.parentElement;
    }
    for (const sel of candidates) {
      try {
        const matches = Array.from(document.querySelectorAll(sel));
        if (!matches.includes(el) || matches.length < 2) continue;
        if (cardishRatio(matches) < 0.55) continue;
        return sel;
      } catch (_) {}
    }
    const region = el.closest("main,article,section");
    if (region) {
      for (const root of scopeRootCandidates(region)) {
        const sel = `${root} ${simple || tag}`;
        try {
          const matches = Array.from(document.querySelectorAll(sel));
          if (matches.includes(el) && matches.length >= 2 && cardishRatio(matches) >= 0.55) return sel;
        } catch (_) {}
      }
    }
    return simple;
  };

  const relSelector = (root, el) => {
    if (!root || !el) return "";
    if (root === el) return "";
    const tag = el.tagName.toLowerCase();
    const candidates = [];
    if (el.id && !randomClassRe.test(el.id)) candidates.push(`#${cssEscape(el.id)}`);
    for (const c of stableClasses(el)) {
      candidates.push(`${tag}.${cssEscape(c)}`);
      candidates.push(`.${cssEscape(c)}`);
    }
    if (tag === "a" && el.querySelector("img")) candidates.push("a:has(img)");
    if (tag === "img") candidates.push("img");
    if (tag === "video" || tag === "audio" || tag === "source") candidates.push(tag);
    candidates.push(tag);
    for (const sel of candidates) {
      try {
        const matches = Array.from(root.querySelectorAll(sel));
        if (matches.includes(el)) return sel;
      } catch (_) {}
    }
    return tag;
  };

  const hrefFrom = (node) => {
    if (!node) return "";
    return node.getAttribute("href")
      || node.getAttribute("data-href")
      || node.getAttribute("data-url")
      || node.getAttribute("data-play-url")
      || node.getAttribute("data-src")
      || "";
  };

  const srcFrom = (node) => {
    if (!node) return "";
    return node.currentSrc
      || node.getAttribute("src")
      || node.getAttribute("data-src")
      || node.getAttribute("data-original")
      || node.getAttribute("data-lazy-src")
      || "";
  };

  const htmlExcerpt = (el) => {
    const clone = el.cloneNode(true);
    for (const bad of clone.querySelectorAll("script, style, noscript")) bad.remove();
    return clone.outerHTML.replace(/\s+/g, " ").slice(0, 2200);
  };

  const signatureFor = (el) => {
    const childTags = Array.from(el.children).slice(0, 8).map(ch => ch.tagName.toLowerCase()).join(">");
    const cls = stableClasses(el).slice(0, 2).join(".");
    return `${el.tagName.toLowerCase()}|${cls}|${childTags}`;
  };

  const looksLikeDuration = (text) => /\b\d{1,2}:\d{2}(?::\d{2})?\b/.test(text);

  const titleCandidates = (root) => {
    const out = [];
    const altTexts = Array.from(root.querySelectorAll("img"))
      .map(img => normText(img.getAttribute("alt") || img.getAttribute("title") || ""))
      .filter(text => text.length >= 4 && text.length <= 180 && !looksLikeDuration(text));

    const altCorroboration = (text) => {
      const normalized = normText(text).toLowerCase();
      if (!normalized || !altTexts.length) return 0;
      let best = 0;
      for (const alt of altTexts) {
        const a = alt.toLowerCase();
        if (!a) continue;
        if (a === normalized) best = Math.max(best, 0.24);
        else if (a.includes(normalized) || normalized.includes(a)) best = Math.max(best, 0.16);
      }
      return best;
    };

    const pushTitle = (node, text, baseScore, source) => {
      text = normText(text);
      if (!node || !text || text.length < 4 || text.length > 180 || looksLikeDuration(text)) return;
      const tag = node.tagName.toLowerCase();
      // Do not use img alt/title as a title selector. Alt text is only corroborating evidence
      // for nearby real text nodes. A selector like a:has(img) must validate against the
      // anchor's own inner/title text, never the nested img alt.
      if (tag === "img") return;
      const selector = relSelector(root, node);
      if (!selector) return;
      const classes = classList(node).join(" ").toLowerCase();
      let score = baseScore + altCorroboration(text);
      if (/title|name|caption|desc/.test(classes)) score += 0.25;
      if (/h[1-6]/.test(tag)) score += 0.2;
      if (tag === "a") score += node.querySelector("img") ? 0.06 : 0.16;
      if (tag === "p" || tag === "span") score += 0.06;
      out.push({ text, selector, score, source, alt_corroborated: altCorroboration(text) > 0 });
    };

    // Use image alt/title only as corroborating evidence. Real title selectors must be text-bearing nodes.
    for (const a of Array.from(root.querySelectorAll("a[href],a[data-href],a[data-url],a[data-play-url]"))) {
      const text = a.getAttribute("title") || normText(a.innerText || a.textContent || "");
      pushTitle(a, text, a.querySelector("img") ? 0.44 : 0.62, "anchor_text");
    }
    const nodes = Array.from(root.querySelectorAll("h1,h2,h3,h4,h5,h6,p,span,div"));
    for (const node of nodes) {
      if (!isVisible(node)) continue;
      pushTitle(node, node.getAttribute("title") || node.innerText || node.textContent || "", 0.34, "visible_text");
    }
    const bestByKey = new Map();
    for (const item of out) {
      const key = `${item.selector}
${item.text}`;
      if (!bestByKey.has(key) || bestByKey.get(key).score < item.score) bestByKey.set(key, item);
    }
    return Array.from(bestByKey.values()).sort((a, b) => b.score - a.score).slice(0, 8);
  };

  const durationCandidates = (root) => {
    const nodes = Array.from(root.querySelectorAll("span,div,p,i,b,em"));
    const out = [];
    for (const node of nodes) {
      const text = normText(node.innerText || node.textContent || "");
      if (!looksLikeDuration(text)) continue;
      out.push({ text, selector: relSelector(root, node), score: 1 });
    }
    return out.slice(0, 5);
  };

  const nodeCandidates = Array.from(document.querySelectorAll("article,li,section,div,a"))
    .filter(el => isVisible(el))
    .filter(el => !el.closest("header,nav,footer"))
    .filter(el => {
      const links = el.matches("a") ? [el] : Array.from(el.querySelectorAll("a[href],a[data-href],a[data-url],a[data-play-url]"));
      const imgs = Array.from(el.querySelectorAll("img, picture, [style*='background-image']"));
      const text = normText(el.innerText || el.textContent || "");
      const r = el.getBoundingClientRect();
      if (r.width > window.innerWidth * 0.98 && r.height > window.innerHeight * 0.85) return false;
      return links.length >= 1 && imgs.length >= 1 && text.length >= 2;
    });

  const grouped = new Map();
  for (const el of nodeCandidates) {
    const selector = scopedCandidateSelector(el);
    const key = selector || signatureFor(el);
    if (!grouped.has(key)) grouped.set(key, []);
    grouped.get(key).push(el);
  }

  const groups = [];
  let groupIndex = 1;
  for (const [selector, nodes] of grouped.entries()) {
    if (nodes.length < 2) continue;
    const visibleNodes = nodes.filter(isVisible);
    if (visibleNodes.length < 2) continue;

    const samples = visibleNodes.slice(0, maxSamples).map((node, index) => {
      const links = Array.from(node.querySelectorAll("a[href],a[data-href],a[data-url],a[data-play-url]"));
      const images = Array.from(node.querySelectorAll("img"));
      return {
        index,
        text: normText(node.innerText || node.textContent || "").slice(0, 500),
        html_excerpt: htmlExcerpt(node),
        bbox: bbox(node),
        links: links.slice(0, 8).map(a => ({
          href: hrefFrom(a),
          text: normText(a.getAttribute("title") || a.innerText || a.textContent || "").slice(0, 240),
          selector: relSelector(node, a),
          has_image: !!a.querySelector("img"),
          classes: classList(a).slice(0, 8)
        })),
        images: images.slice(0, 6).map(img => ({
          src: srcFrom(img),
          alt: normText(img.getAttribute("alt") || ""),
          selector: relSelector(node, img),
          width: Number(img.naturalWidth || img.width || 0),
          height: Number(img.naturalHeight || img.height || 0),
          role: "thumbnail"
        })),
        title_candidates: titleCandidates(node),
        duration_candidates: durationCandidates(node)
      };
    });

    const linkCount = samples.reduce((acc, s) => acc + (s.links.length ? 1 : 0), 0);
    const imgCount = samples.reduce((acc, s) => acc + (s.images.length ? 1 : 0), 0);
    const titleCount = samples.reduce((acc, s) => acc + (s.title_candidates.length ? 1 : 0), 0);
    const avgY = visibleNodes.slice(0, 8).reduce((acc, n) => acc + n.getBoundingClientRect().y, 0) / Math.min(visibleNodes.length, 8);
    const avgArea = visibleNodes.slice(0, 8).reduce((acc, n) => {
      const r = n.getBoundingClientRect();
      return acc + r.width * r.height;
    }, 0) / Math.min(visibleNodes.length, 8);
    const region = pageRegion(visibleNodes[0]);
    const repetition = Math.min(1, visibleNodes.length / 12);
    const fieldCompleteness = (linkCount + imgCount + titleCount) / Math.max(1, samples.length * 3);
    const visualProminence = Math.min(1, avgArea / 25000) * (region === "main" || region === "article" || region === "section" || region === "body" ? 1 : 0.55);
    const aboveFooter = avgY < (document.documentElement.scrollHeight * 0.85) ? 1 : 0.55;
    const score = repetition * 0.35 + fieldCompleteness * 0.40 + visualProminence * 0.15 + aboveFooter * 0.10;

    groups.push({
      group_id: `G${groupIndex++}`,
      selector,
      tag: visibleNodes[0].tagName.toLowerCase(),
      count: nodes.length,
      visible_count: visibleNodes.length,
      layout: inferLayout(visibleNodes.slice(0, 8)),
      page_region: region,
      score,
      score_breakdown: { repetition, field_completeness: fieldCompleteness, visual_prominence: visualProminence, page_position: aboveFooter },
      samples,
      negative_signals: region === "aside" ? ["inside aside"] : []
    });
  }

  function inferLayout(nodes) {
    if (nodes.length < 2) return "single";
    const xs = nodes.map(n => Math.round(n.getBoundingClientRect().x));
    const ys = nodes.map(n => Math.round(n.getBoundingClientRect().y));
    const uniqueRows = new Set(ys.map(y => Math.round(y / 20))).size;
    const uniqueCols = new Set(xs.map(x => Math.round(x / 20))).size;
    if (uniqueRows > 1 && uniqueCols > 1) return "grid";
    if (uniqueRows > 1) return "vertical-list";
    return "horizontal-list";
  }

  return {
    title: document.title || null,
    final_url: location.href,
    viewport: { width: window.innerWidth, height: window.innerHeight },
    groups: groups.sort((a, b) => b.score - a.score).slice(0, maxGroups),
    html_skeleton: Array.from(document.querySelectorAll("main,article,section,ul,ol,div,a,img,video,audio,source,iframe,button"))
      .slice(0, 600)
      .map(el => {
        const tag = el.tagName.toLowerCase();
        const cls = classList(el).slice(0, 4).join(" ");
        const href = hrefFrom(el);
        const src = srcFrom(el);
        const text = normText(el.innerText || el.textContent || "").slice(0, 80);
        return `<${tag}${cls ? ` class="${cls}"` : ""}${href ? ` href="${href}"` : ""}${src ? ` src="${src}"` : ""}>${text ? ` text="${text}"` : ""}`;
      })
      .filter(line => /href=|src=|video|audio|iframe|play|watch|播放|episode|第|<main|<article|<section|<ul|<ol/.test(line.toLowerCase()))
      .slice(0, 260)
      .join("\n")
  };
}
"""


DETAIL_EVIDENCE_JS = r"""
() => {
  const cssEscape = (value) => {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  };
  const normText = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const classList = (el) => Array.from(el.classList || []).filter(Boolean);
  const randomClassRe = /(^[a-zA-Z0-9_-]{12,}$|css-[a-z0-9]+|_[a-z0-9]{6,}|__[a-z0-9]{6,}|^svelte-|^astro-|^ng-|^v-[a-f0-9]+$)/i;
  const generic = new Set(["active","box","card","clearfix","col","container","content","current","flex","grid","hidden","item","lazy","left","link","list","media","nav","right","row","selected","show","thumb","thumbnail","title","video","visible","wrapper"]);

  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 8 && r.height >= 8 && r.bottom >= 0 && r.right >= 0;
  };

  const selectorFor = (el) => {
    if (!el || !el.tagName) return "";
    const tag = el.tagName.toLowerCase();
    if (el.id && !randomClassRe.test(el.id)) {
      const sel = `#${cssEscape(el.id)}`;
      if (document.querySelectorAll(sel).length === 1) return sel;
    }
    const stable = classList(el).filter(c => !generic.has(c) && !randomClassRe.test(c)).slice(0, 3);
    if (stable.length) return `${tag}.${stable.map(cssEscape).join(".")}`;
    const classes = classList(el).filter(c => !randomClassRe.test(c)).slice(0, 2);
    if (classes.length) return `${tag}.${classes.map(cssEscape).join(".")}`;
    return tag;
  };

  const hrefFrom = (node) => node?.getAttribute("href")
    || node?.getAttribute("data-href")
    || node?.getAttribute("data-url")
    || node?.getAttribute("data-play-url")
    || node?.getAttribute("data-src")
    || "";

  const srcFrom = (node) => node?.currentSrc
    || node?.getAttribute("src")
    || node?.getAttribute("data-src")
    || node?.getAttribute("data-original")
    || node?.getAttribute("data-lazy-src")
    || "";

  const mediaNodes = Array.from(document.querySelectorAll("video,audio,source")).map(node => ({
    tag: node.tagName.toLowerCase(),
    selector: selectorFor(node),
    src: srcFrom(node),
    poster: node.getAttribute("poster") || "",
    text: normText(node.innerText || node.textContent || "")
  }));

  const playerNodes = Array.from(document.querySelectorAll(
    "video,audio,iframe,[class*='player'],[id*='player'],[class*='video'],[id*='video'],.vjs-tech,.jwplayer"
  )).filter(isVisible).slice(0, 12).map(node => {
    const r = node.getBoundingClientRect();
    return {
      tag: node.tagName.toLowerCase(),
      selector: selectorFor(node),
      src: srcFrom(node),
      classes: classList(node).slice(0, 8),
      text: normText(node.innerText || node.textContent || "").slice(0, 160),
      bbox: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }
    };
  });

  const playRe = /(play|watch|player|btn-play|播放|立即播放|观看|正片|▶)/i;
  const episodeRe = /(episode|ep\.?|第\s*\d+|第[一二三四五六七八九十百]+|集|章|part|season|s\d+e\d+)/i;

  const anchors = Array.from(document.querySelectorAll("a[href],a[data-href],a[data-url],a[data-play-url]"));
  const playLinks = anchors.filter(a => playRe.test([hrefFrom(a), normText(a.innerText || a.textContent || ""), classList(a).join(" ")].join(" ")))
    .slice(0, 50)
    .map(a => ({ href: hrefFrom(a), text: normText(a.innerText || a.textContent || "").slice(0, 160), selector: selectorFor(a), has_image: !!a.querySelector("img"), classes: classList(a).slice(0, 8) }));

  const episodeLinks = anchors.filter(a => episodeRe.test([hrefFrom(a), normText(a.innerText || a.textContent || ""), classList(a).join(" ")].join(" ")))
    .slice(0, 80)
    .map(a => ({ href: hrefFrom(a), text: normText(a.innerText || a.textContent || "").slice(0, 160), selector: selectorFor(a), has_image: !!a.querySelector("img"), classes: classList(a).slice(0, 8) }));

  const playButtons = Array.from(document.querySelectorAll("button,a,div,span,[role='button']"))
    .filter(isVisible)
    .filter(node => playRe.test([normText(node.getAttribute("aria-label") || ""), normText(node.getAttribute("title") || ""), normText(node.innerText || node.textContent || ""), classList(node).join(" ")].join(" ")))
    .slice(0, 20)
    .map(node => ({
      tag: node.tagName.toLowerCase(),
      selector: selectorFor(node),
      text: normText(node.innerText || node.textContent || node.getAttribute("aria-label") || node.getAttribute("title") || "").slice(0, 160),
      classes: classList(node).slice(0, 8)
    }));

  const iframes = Array.from(document.querySelectorAll("iframe"))
    .slice(0, 20)
    .map(node => ({ selector: selectorFor(node), src: srcFrom(node), text: normText(node.getAttribute("title") || "") }));

  return {
    title: document.title || null,
    final_url: location.href,
    media_nodes: mediaNodes,
    player_nodes: playerNodes,
    play_links: playLinks,
    episode_links: episodeLinks,
    play_buttons: playButtons,
    iframes
  };
}
"""


LISTING_VALIDATE_JS = r"""
({ rule, limit }) => {
  const normText = (value) => String(value || "").replace(/\s+/g, " ").trim();
  const isVisible = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const style = window.getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= 8 && r.height >= 8 && r.bottom >= 0 && r.right >= 0;
  };
  const hrefFrom = (node) => node?.getAttribute("href")
    || node?.getAttribute("data-href")
    || node?.getAttribute("data-url")
    || node?.getAttribute("data-play-url")
    || node?.getAttribute("data-src")
    || "";

  const candidateSelector = rule.candidate_selector || "a:has(img)";
  const linkSelector = rule.candidate_link_selector || "";
  const titleSelector = rule.title_selector || "";
  const thumbSelector = rule.thumbnail_selector || "";
  const durationSelector = rule.duration_selector || "";
  let nodes = [];
  let error = null;
  try {
    nodes = Array.from(document.querySelectorAll(candidateSelector)).slice(0, limit);
  } catch (e) {
    error = String(e);
  }

  const rows = nodes.map((node, index) => {
    const linkNode = linkSelector
      ? (node.matches && node.matches(linkSelector) ? node : node.querySelector(linkSelector))
      : (node.matches && node.matches("a[href]") ? node : node.querySelector("a[href],a[data-href],a[data-url],a[data-play-url]"));
    const titleNode = titleSelector
      ? (node.matches && node.matches(titleSelector) ? node : node.querySelector(titleSelector))
      : (linkNode || node);
    const thumbNode = thumbSelector
      ? (node.matches && node.matches(thumbSelector) ? node : node.querySelector(thumbSelector))
      : node.querySelector("img");
    const durationNode = durationSelector
      ? (node.matches && node.matches(durationSelector) ? node : node.querySelector(durationSelector))
      : null;
    const titleTextFrom = (target) => {
      if (!target) return "";
      const tag = target.tagName?.toLowerCase?.() || "";
      if (tag === "img") return ""; // img alt is not title text; keep it out of validation.
      return normText(
        target.getAttribute?.("title")
        || target.getAttribute?.("aria-label")
        || target.innerText
        || target.textContent
        || ""
      );
    };
    let title = "";
    if (titleSelector) {
      // Validate exactly what title_selector selects. For a:has(img), this is the anchor's
      // own text/title, not the nested image alt.
      title = titleTextFrom(titleNode);
    } else {
      title = titleTextFrom(linkNode) || titleTextFrom(node);
    }
    return {
      index,
      visible: isVisible(node),
      href: hrefFrom(linkNode),
      title,
      thumb: thumbNode?.currentSrc || thumbNode?.getAttribute?.("src") || thumbNode?.getAttribute?.("data-src") || "",
      duration: normText(durationNode?.innerText || durationNode?.textContent || ""),
    };
  });
  return { error, candidate_count: nodes.length, visible_count: nodes.filter(isVisible).length, rows };
}
"""


def to_plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, list):
        return [to_plain(v) for v in value]
    if isinstance(value, tuple):
        return [to_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_plain(v) for k, v in value.items()}
    return value


def counter_top(values: list[str], n: int = 8) -> list[tuple[str, int]]:
    return [(k, v) for k, v in Counter(v for v in values if v).most_common(n)]


def choose_most_common_selector(selector_counts: list[tuple[str, int]]) -> str | None:
    for selector, count in selector_counts:
        if not selector or selector in {"a", "div", "span", "li", "section"}:
            continue
        if count >= 1:
            return selector
    return None


def convert_raw_group(raw: dict[str, Any], base_url: str) -> CandidateGroup:
    samples: list[CardSample] = []
    link_selectors: list[str] = []
    title_selectors: list[str] = []
    thumbnail_selectors: list[str] = []
    duration_selectors: list[str] = []
    href_shapes: list[str] = []

    for sample_raw in raw.get("samples", []) or []:
        links: list[LinkEvidence] = []
        for link_raw in sample_raw.get("links", []) or []:
            abs_url = normalize_url(link_raw.get("href", ""), base_url)
            if not abs_url:
                continue
            selector = str(link_raw.get("selector") or "")
            href_shape = url_shape(abs_url)
            link_selectors.append(selector)
            href_shapes.append(href_shape)
            links.append(LinkEvidence(
                href=str(link_raw.get("href") or ""),
                abs_url=abs_url,
                text=normalized_text(str(link_raw.get("text") or "")),
                selector=selector,
                has_image=bool(link_raw.get("has_image")),
                classes=[str(c) for c in (link_raw.get("classes") or [])],
                href_shape=href_shape,
            ))

        images: list[ImageEvidence] = []
        for image_raw in sample_raw.get("images", []) or []:
            abs_url = normalize_url(image_raw.get("src", ""), base_url)
            selector = str(image_raw.get("selector") or "img")
            if selector:
                thumbnail_selectors.append(selector)
            images.append(ImageEvidence(
                src=str(image_raw.get("src") or ""),
                abs_url=abs_url,
                alt=normalized_text(str(image_raw.get("alt") or "")),
                selector=selector,
                width=int(image_raw.get("width") or 0),
                height=int(image_raw.get("height") or 0),
                role=str(image_raw.get("role") or "thumbnail"),
            ))

        titles: list[TextEvidence] = []
        for title_raw in sample_raw.get("title_candidates", []) or []:
            selector = str(title_raw.get("selector") or "")
            text = normalized_text(str(title_raw.get("text") or ""))
            if not selector or not text:
                continue
            title_selectors.append(selector)
            titles.append(TextEvidence(text=text, selector=selector, score=safe_float(title_raw.get("score"), 0.0)))

        durations: list[TextEvidence] = []
        for dur_raw in sample_raw.get("duration_candidates", []) or []:
            selector = str(dur_raw.get("selector") or "")
            text = normalized_text(str(dur_raw.get("text") or ""))
            if selector:
                duration_selectors.append(selector)
            durations.append(TextEvidence(text=text, selector=selector, score=safe_float(dur_raw.get("score"), 1.0)))

        samples.append(CardSample(
            index=int(sample_raw.get("index") or 0),
            text=normalized_text(str(sample_raw.get("text") or ""))[:500],
            html_excerpt=str(sample_raw.get("html_excerpt") or "")[:2200],
            bbox={k: safe_float(v) for k, v in (sample_raw.get("bbox") or {}).items()},
            links=links,
            images=images,
            title_candidates=titles,
            duration_candidates=durations,
        ))

    return CandidateGroup(
        group_id=str(raw.get("group_id") or ""),
        selector=str(raw.get("selector") or ""),
        tag=str(raw.get("tag") or ""),
        count=int(raw.get("count") or 0),
        visible_count=int(raw.get("visible_count") or 0),
        layout=str(raw.get("layout") or "unknown"),
        page_region=str(raw.get("page_region") or "unknown"),
        score=safe_float(raw.get("score"), 0.0),
        score_breakdown={k: safe_float(v) for k, v in (raw.get("score_breakdown") or {}).items()},
        link_selector_hints=counter_top(link_selectors),
        title_selector_hints=counter_top(title_selectors),
        thumbnail_selector_hints=counter_top(thumbnail_selectors),
        duration_selector_hints=counter_top(duration_selectors),
        href_shapes=counter_top(href_shapes),
        samples=samples,
        negative_signals=[str(v) for v in raw.get("negative_signals", []) or []],
    )


def collect_page_evidence(
    runtime: BrowserRuntime,
    url: str,
    *,
    user_agent: str,
    timeout: float,
    max_groups: int,
    max_samples: int,
    scroll_steps: int,
    desktop: bool,
) -> PageEvidence:
    LOGGER.info("collect page evidence start url=%s", url)
    context = runtime.new_context(user_agent=user_agent, desktop=desktop)
    page = context.new_page()
    network_media: list[dict[str, Any]] = []
    collect_network_media(page, network_media, url)
    lazy_load_observed = False
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        page.wait_for_timeout(900)
        before_count = page.evaluate("() => document.querySelectorAll('a, img').length")
        auto_scroll(page, scroll_steps, 450)
        after_count = page.evaluate("() => document.querySelectorAll('a, img').length")
        lazy_load_observed = after_count > before_count + 5

        raw = page.evaluate(LISTING_EVIDENCE_JS, {"maxGroups": max_groups, "maxSamples": max_samples})
        final_url = str(raw.get("final_url") or page.url)
        groups = [convert_raw_group(group, final_url) for group in (raw.get("groups") or [])]

        evidence = PageEvidence(
            requested_url=url,
            final_url=final_url,
            title=raw.get("title"),
            viewport={k: int(v) for k, v in (raw.get("viewport") or {}).items()},
            candidate_groups=groups,
            network_media_after_load=dedupe_media_rows(network_media, final_url),
            resource_summary=Counter(row.get("kind", "unknown") for row in network_media),
            lazy_load_observed=lazy_load_observed,
            html_skeleton=str(raw.get("html_skeleton") or "")[:40000],
            collected_at=now_string(),
        )
        LOGGER.info("collect page evidence done final_url=%s groups=%d network_media=%d lazy=%s", final_url, len(groups), len(evidence.network_media_after_load), lazy_load_observed)
        return evidence
    finally:
        context.close()


def dedupe_media_rows(rows: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        url = normalize_url(str(row.get("url") or ""), base_url)
        if not url:
            continue
        key = strip_tracking_query(url)
        if key in seen:
            continue
        seen.add(key)
        copied = dict(row)
        copied["url"] = url
        if "kind" not in copied or copied["kind"] == "unknown":
            copied["kind"] = media_kind_from_url(url)
        out.append(copied)
    return out[:80]


def primary_link_selector(group: CandidateGroup) -> str | None:
    # Prefer image anchors when thumbnail link and title link point to the same detail page.
    for selector, count in group.link_selector_hints:
        if selector == "a:has(img)" and count >= max(1, len(group.samples) // 2):
            return selector
    selector = choose_most_common_selector(group.link_selector_hints)
    if selector:
        return selector
    return "a:has(img)"


def primary_title_selector(group: CandidateGroup) -> str | None:
    scored: dict[str, float] = defaultdict(float)
    counts: Counter[str] = Counter()
    for sample in group.samples:
        for candidate in sample.title_candidates:
            selector = candidate.selector
            if not selector:
                continue
            counts[selector] += 1
            bonus = 0.0
            lowered = selector.lower()
            # Image alt is only corroboration upstream; never choose img as a title selector.
            if lowered == "img" or lowered.endswith(" img") or " img" in lowered:
                continue
            if lowered.startswith("a") or " a" in lowered or "a:" in lowered:
                bonus += 0.10
            if any(token in lowered for token in ("title", "name", "caption", "h2", "h3", "h4")):
                bonus += 0.20
            if lowered in {"div", "span"}:
                bonus -= 0.12
            scored[selector] += max(candidate.score, 0.1) + bonus
    if scored:
        ranked = sorted(scored, key=lambda sel: (scored[sel], counts[sel]), reverse=True)
        for selector in ranked:
            lowered = selector.lower()
            if selector not in {"div", "span"} and lowered != "img" and " img" not in lowered:
                return selector
    return choose_most_common_selector(group.title_selector_hints)


def primary_thumbnail_selector(group: CandidateGroup) -> str | None:
    for selector, _ in group.thumbnail_selector_hints:
        if selector:
            return selector
    return "img" if any(sample.images for sample in group.samples) else None


def primary_duration_selector(group: CandidateGroup) -> str | None:
    return choose_most_common_selector(group.duration_selector_hints)


def guess_page_intent(evidence: PageEvidence, group: CandidateGroup) -> str:
    title = (evidence.title or "").lower()
    href_shapes = " ".join(shape for shape, _ in group.href_shapes).lower()
    if any(token in title + " " + href_shapes for token in ("gallery", "photo", "image", "album", "photos")):
        return "image_gallery"
    if any(token in title + " " + href_shapes for token in ("audio", "music", "podcast", "mp3")):
        return "audio_listing"
    return "video_listing"


def local_hypotheses(evidence: PageEvidence, max_items: int, limit: int = 5) -> list[RuleHypothesis]:
    out: list[RuleHypothesis] = []
    for idx, group in enumerate(evidence.candidate_groups[:limit], start=1):
        intent = guess_page_intent(evidence, group)
        media_type = "image" if intent == "image_gallery" else "audio" if intent == "audio_listing" else "video"
        rule: dict[str, Any] = {
            "source": evidence.final_url,
            "candidate_selector": group.selector or "a:has(img)",
            "candidate_link_selector": primary_link_selector(group),
            "media_type": media_type,
            "projection": "flat" if intent == "image_gallery" else "by-item",
            "max_items": max_items,
            "force_network_sniff": False,
            "fast_mode": True,
        }
        title_selector = primary_title_selector(group)
        if title_selector:
            rule["title_selector"] = title_selector
        thumb_selector = primary_thumbnail_selector(group)
        if thumb_selector:
            rule["thumbnail_selector"] = thumb_selector
        duration_selector = primary_duration_selector(group)
        if duration_selector:
            rule["duration_selector"] = duration_selector
        out.append(RuleHypothesis(
            id=f"L{idx}",
            source="local",
            page_intent=intent,
            rule_draft=prefer_scoped_candidate_selector(sanitize_rule(rule, evidence.final_url, max_items), evidence, max_items),
            expected_chain=["listing_item", "detail_page", "player_or_media"],
            needs_probe=["selector_dry_run", "detail_page_probe", "network_probe_after_click"],
            confidence=clamp(group.score, 0.1, 0.9),
            risks=group.negative_signals[:],
        ))
    if not out:
        rule = sanitize_rule({
            "source": evidence.final_url,
            "candidate_selector": "a:has(img)",
            "candidate_link_selector": "a:has(img)",
            "media_type": "video",
            "projection": "by-item",
            "max_items": max_items,
            "force_network_sniff": True,
            "fast_mode": True,
        }, evidence.final_url, max_items)
        out.append(RuleHypothesis(
            id="L1",
            source="local",
            page_intent="video_listing",
            rule_draft=rule,
            expected_chain=["listing_item", "detail_page", "player_or_media"],
            needs_probe=["selector_dry_run", "detail_page_probe", "network_probe_after_click"],
            confidence=0.25,
            risks=["No strong repeated card group was found; using broad a:has(img) fallback."],
        ))
    return out


def candidate_selector_is_scoped(selector: str) -> bool:
    selector = str(selector or "").strip()
    return bool(re.search(r'[#.]?[A-Za-z0-9_-]+\s+[A-Za-z#.:\[>]', selector)) or '>' in selector


def prefer_scoped_candidate_selector(rule: dict[str, Any], evidence: PageEvidence, max_items: int) -> dict[str, Any]:
    """Replace overly broad AI/local candidate selectors with the closest scoped group selector."""
    candidate = str(rule.get("candidate_selector") or "").strip()
    if not candidate or candidate_selector_is_scoped(candidate):
        return sanitize_rule(rule, evidence.final_url, max_items)
    for group in evidence.candidate_groups:
        scoped = str(group.selector or "").strip()
        if not scoped or not candidate_selector_is_scoped(scoped):
            continue
        tail = scoped.split()[-1].strip()
        if candidate == tail or candidate == group.tag or candidate in scoped or candidate == f".{tail.split('.')[-1]}":
            patched = dict(rule)
            patched["candidate_selector"] = scoped
            return sanitize_rule(patched, evidence.final_url, max_items)
    # If no exact mapping is found, prefer the best browser-mined scoped selector over a broad fallback.
    if candidate in {"a:has(img)", "li", "div", "article", "section", "a"}:
        for group in evidence.candidate_groups:
            if group.selector and candidate_selector_is_scoped(group.selector):
                patched = dict(rule)
                patched["candidate_selector"] = group.selector
                return sanitize_rule(patched, evidence.final_url, max_items)
    return sanitize_rule(rule, evidence.final_url, max_items)


def build_hypothesis_prompt(evidence: PageEvidence, max_items: int) -> list[dict[str, str]]:
    payload = {
        "page": {
            "requested_url": evidence.requested_url,
            "final_url": evidence.final_url,
            "title": evidence.title,
            "viewport": evidence.viewport,
            "lazy_load_observed": evidence.lazy_load_observed,
        },
        "supported_rule_keys": list(SUPPORTED_RULE_KEYS),
        "rule_generation_constraints": rule_generation_constraints(),
        "candidate_groups": compact_candidate_groups(evidence.candidate_groups),
        "network_media_after_load": evidence.network_media_after_load[:20],
        "html_skeleton": evidence.html_skeleton[:18000],
        "default_max_items": max_items,
    }
    system = (
        "You infer Web Media Projection Resolver .wm rule hypotheses from browser-rendered evidence. "
        "Return one JSON object only, without markdown. Do not finalize one rule yet. "
        "Use only supported keys inside rule_draft. Generate multiple hypotheses when ambiguous. "
        "Treat the payload as evidence, not conclusions."
    )
    user = (
        "Human workflow to emulate: visually locate repeated media cards; inspect a card container, detail link, "
        "title, thumbnail; then probe detail pages for player, episode links, media nodes, and network streams.\n\n"
        "Propose up to 5 rule hypotheses. Use ids A1, A2, ... for AI hypotheses. For each hypothesis include id, page_intent, rule_draft, "
        "expected_chain, needs_probe, confidence, risks.\n\n"
        "Return JSON shape:\n"
        "{\n"
        '  "page_intent": "video_listing|image_gallery|audio_listing|download_list|unknown",\n'
        '  "hypotheses": [\n'
        '    {"id":"A1","page_intent":"...","rule_draft":{},"expected_chain":[],"needs_probe":[],"confidence":0.0,"risks":[]}\n'
        "  ]\n"
        "}\n\n"
        "Evidence:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_final_prompt(
    evidence: PageEvidence,
    hypotheses: list[RuleHypothesis],
    validations: list[HypothesisValidation],
    max_items: int,
) -> list[dict[str, str]]:
    payload = {
        "page": {
            "requested_url": evidence.requested_url,
            "final_url": evidence.final_url,
            "title": evidence.title,
            "lazy_load_observed": evidence.lazy_load_observed,
        },
        "supported_rule_keys": list(SUPPORTED_RULE_KEYS),
        "rule_generation_constraints": rule_generation_constraints(),
        "hypotheses": [to_plain(h) for h in hypotheses],
        "validation_results": [compact_validation(v) for v in validations],
        "default_max_items": max_items,
    }
    system = (
        "You finalize Web Media Projection Resolver .wm rules from tested hypotheses. "
        "Return one JSON object only, without markdown. Use only supported keys inside rule. "
        "Prefer validated selectors over plausible selectors. Remove fields that failed validation."
    )
    user = (
        "Choose or repair the best rule based on validation results.\n\n"
        "Important rules:\n"
        "- Detail hop policy is strict: if listing item detail pages already expose primary media, do not add a single detail_url_selector hop.\n"
        "- If detail pages already expose primary media but also expose episode/part links, add detail_url_selector with detail_url_mode=expand.\n"
        "- If detail pages do not expose primary media and expose stable play/episode links, add detail_url_selector; use expand only for episode/multiple links, otherwise single is allowed.\n"
        "- Never add detail_url_selector merely because the listing card uses candidate_link_selector; candidate_link_selector already reaches the item detail page.\n"
        "- play_button_selector and media_selector are disabled in this script version; do not output them.\n"
        "- Set fast_mode=true; this script will enforce it.\n"
        "- Do not treat listing thumbnails or intermediate-page poster images as primary media for video pages.\n"
        "- Prefer media_type=video for video sites unless validation proves image/audio intent.\n"
        "- Omit optional selectors when their coverage is weak.\n\n"
        "Return JSON shape:\n"
        "{\n"
        '  "rule": {},\n'
        '  "confidence": "0.0-1.0 or label",\n'
        '  "reasoning": "",\n'
        '  "detail_url_examples": [],\n'
        '  "warnings": []\n'
        "}\n\n"
        "Validation payload:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def rule_generation_constraints() -> list[str]:
    return [
        "candidate_selector should select the repeated media card container, not page navigation or footer.",
        "candidate_selector should prefer scoped selectors such as #container li, .list-content li, or .video-list article over a bare li/div/card selector.",
        "candidate_selector may be a:has(img) only as a fallback when the anchor itself is the card and no scoped card selector exists.",
        "candidate_link_selector should select the detail/intermediate page link inside a card.",
        "title_selector, thumbnail_selector, duration_selector should be relative to candidate_selector.",
        "media_selector is disabled for now and must not be emitted.",
        "media_type controls which resources count as media and defaults to video.",
        "For video rules, listing/intermediate images are thumbnails/posters and must not count as primary media.",
        "Use projection=flat for image galleries or simple download lists; use projection=by-item for video/audio listings.",
        "If listing item URLs lead to pages with no primary media but stable play/episode links, emit detail_url_selector.",
        "If listing item URLs lead to pages with primary media, do not emit a single detail_url_selector hop.",
        "If playable detail pages also expose episode/part links, emit detail_url_selector with detail_url_mode=expand.",
        "Use detail_url_mode=expand for episode lists or multiple next links; use single only for true no-media intermediate pages with one next play link.",
        "detail_url_selector should select the next page link, such as a.btn-play or a[href*='/play/']; never use generic a.",
        "detail_url_stop_when_media_found defaults to false.",
        "play_button_selector is disabled for now and must not be emitted; do not rely on click-play probing.",
        "fast_mode must always be true.",
        "If rendered content appears after JS/lazy load, set selector_wait_timeout to 1.5 or 3.0.",
        "Only set force_desktop_mode=true when the desktop DOM is clearly required.",
        "Do not emit unsupported fields such as click_strategy, candidate_container_selector, candidate_title_selector, candidate_thumbnail_selector, media_selector, play_button_selector, or manifest_types.",
    ]


def compact_candidate_groups(groups: list[CandidateGroup]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for group in groups[:8]:
        output.append({
            "group_id": group.group_id,
            "selector": group.selector,
            "tag": group.tag,
            "count": group.count,
            "visible_count": group.visible_count,
            "layout": group.layout,
            "page_region": group.page_region,
            "score": round(group.score, 3),
            "score_breakdown": {k: round(v, 3) for k, v in group.score_breakdown.items()},
            "link_selector_hints": group.link_selector_hints,
            "title_selector_hints": group.title_selector_hints,
            "thumbnail_selector_hints": group.thumbnail_selector_hints,
            "duration_selector_hints": group.duration_selector_hints,
            "href_shapes": group.href_shapes,
            "sample_items": [
                {
                    "text": sample.text[:260],
                    "bbox": sample.bbox,
                    "links": [to_plain(link) for link in sample.links[:4]],
                    "images": [to_plain(image) for image in sample.images[:3]],
                    "title_candidates": [to_plain(title) for title in sample.title_candidates[:3]],
                    "duration_candidates": [to_plain(dur) for dur in sample.duration_candidates[:3]],
                    "html_excerpt": sample.html_excerpt[:900],
                }
                for sample in group.samples[:4]
            ],
            "negative_signals": group.negative_signals,
        })
    return output


def compact_validation(validation: HypothesisValidation) -> dict[str, Any]:
    return {
        "hypothesis_id": validation.hypothesis_id,
        "quality_score": round(validation.quality_score, 3),
        "listing": to_plain(validation.listing),
        "detail_probes": [
            {
                "item_title": probe.item_title,
                "item_url": probe.item_url,
                "final_url": probe.final_url,
                "status": probe.status,
                "page_kind": probe.page_kind,
                "page_title": probe.title,
                "title_match_score": probe.title_match_score,
                "title_in_page_title": probe.title_in_page_title,
                "dom_media": probe.dom_media[:8],
                "network_media_after_load": probe.network_media_after_load[:8],
                "network_media_after_click": probe.network_media_after_click[:8],
                "player_candidates": probe.player_candidates[:5],
                "play_button_candidates": probe.play_button_candidates[:5],
                "clicked_play_selector": probe.clicked_play_selector,
                "episode_links": [to_plain(link) for link in probe.episode_links[:10]],
                "play_links": [to_plain(link) for link in probe.play_links[:10]],
                "iframe_candidates": probe.iframe_candidates[:5],
                "suggested_detail_selector": probe.suggested_detail_selector,
                "suggested_detail_mode": probe.suggested_detail_mode,
                "has_primary_media": probe_has_primary_media(probe, "video"),
                "primary_media_count": len(probe_primary_media_rows(probe, "video")),
                "episode_link_count": len(probe.episode_links),
                "play_link_count": len(probe.play_links),
                "error": probe.error,
            }
            for probe in validation.detail_probes
        ],
        "suggested_repairs": validation.suggested_repairs,
        "warnings": validation.warnings,
    }


def call_chat_completion(
    messages: list[dict[str, str]],
    *,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
    use_response_format: bool,
) -> dict[str, Any]:
    LOGGER.info("AI request start model=%s response_format=%s", model, use_response_format)
    endpoint = base_url.rstrip("/") + "/chat/completions"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.1,
    }
    if use_response_format:
        body["response_format"] = {"type": "json_object"}
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    decoded = json.loads(raw.decode("utf-8"))
    content = decoded["choices"][0]["message"]["content"]
    return extract_json_object(content)


def extract_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError("AI response does not contain a JSON object")
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(text[start:index + 1])
                if not isinstance(value, dict):
                    raise ValueError("AI response JSON root is not an object")
                return value
    raise ValueError("AI response JSON object is incomplete")


def ai_hypotheses_or_empty(
    evidence: PageEvidence,
    args: argparse.Namespace,
) -> list[RuleHypothesis]:
    if args.no_ai or not args.api_key:
        return []
    messages = build_hypothesis_prompt(evidence, args.max_items)
    try:
        result = call_chat_completion(
            messages,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
            use_response_format=not args.no_response_format,
        )
    except urllib.error.HTTPError:
        if args.no_response_format:
            LOGGER.exception("AI hypothesis request failed")
            return []
        try:
            result = call_chat_completion(
                messages,
                api_key=args.api_key,
                base_url=args.base_url,
                model=args.model,
                timeout=args.timeout,
                use_response_format=False,
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception("AI hypothesis retry failed")
            return []
    except Exception:  # noqa: BLE001
        LOGGER.exception("AI hypothesis request failed")
        return []

    raw_list = result.get("hypotheses") if isinstance(result.get("hypotheses"), list) else []
    out: list[RuleHypothesis] = []
    for idx, raw in enumerate(raw_list[:5], start=1):
        if not isinstance(raw, dict):
            continue
        raw_rule = raw.get("rule_draft") if isinstance(raw.get("rule_draft"), dict) else {}
        rule = prefer_scoped_candidate_selector(sanitize_rule(raw_rule, evidence.final_url, args.max_items), evidence, args.max_items)
        out.append(RuleHypothesis(
            id=f"A{idx}",
            source="ai",
            page_intent=str(raw.get("page_intent") or result.get("page_intent") or "unknown"),
            rule_draft=rule,
            expected_chain=[str(v) for v in raw.get("expected_chain", []) if v],
            needs_probe=[str(v) for v in raw.get("needs_probe", []) if v],
            confidence=clamp(safe_float(raw.get("confidence"), 0.5), 0.0, 1.0),
            risks=[str(v) for v in raw.get("risks", []) if v],
        ))
    return out


def merge_hypotheses(ai_h: list[RuleHypothesis], local_h: list[RuleHypothesis]) -> list[RuleHypothesis]:
    seen: set[tuple[str, str, str]] = set()
    out: list[RuleHypothesis] = []
    for h in [*ai_h, *local_h]:
        key = (
            str(h.rule_draft.get("candidate_selector") or ""),
            str(h.rule_draft.get("candidate_link_selector") or ""),
            str(h.rule_draft.get("media_type") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(h)
    ai_i = local_i = 1
    used_ids: set[str] = set()
    for h in out:
        prefix = "A" if h.source == "ai" else "L"
        if h.id and h.id.startswith(prefix) and h.id not in used_ids:
            used_ids.add(h.id)
            continue
        if prefix == "A":
            while f"A{ai_i}" in used_ids:
                ai_i += 1
            h.id = f"A{ai_i}"
            used_ids.add(h.id)
        else:
            while f"L{local_i}" in used_ids:
                local_i += 1
            h.id = f"L{local_i}"
            used_ids.add(h.id)
    return out[:8]


def validate_listing(
    runtime: BrowserRuntime,
    url: str,
    rule: dict[str, Any],
    *,
    user_agent: str,
    timeout: float,
    limit: int,
    desktop: bool,
) -> ListingValidation:
    context = runtime.new_context(user_agent=user_agent, desktop=desktop)
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        page.wait_for_timeout(max(500, int(float(rule.get("selector_wait_timeout", 0) or 0) * 1000)))
        raw = page.evaluate(LISTING_VALIDATE_JS, {"rule": rule, "limit": limit})
        errors: list[str] = []
        if raw.get("error"):
            errors.append(str(raw["error"]))
        rows = raw.get("rows") or []
        sample_items: list[dict[str, str]] = []
        href_shapes: list[str] = []
        for row in rows:
            abs_url = normalize_url(row.get("href", ""), page.url)
            if not abs_url or not is_plausible_detail_url(abs_url):
                continue
            href_shapes.append(url_shape(abs_url))
            sample_items.append({
                "href": abs_url,
                "title": normalized_text(str(row.get("title") or ""))[:180],
                "thumbnail": normalize_url(str(row.get("thumb") or ""), page.url),
                "duration": normalized_text(str(row.get("duration") or "")),
            })
        visible_count = int(raw.get("visible_count") or 0)
        candidate_count = int(raw.get("candidate_count") or 0)
        denom = max(1, min(candidate_count, limit))
        link_coverage = len(sample_items) / denom
        title_coverage = sum(1 for item in sample_items if item.get("title")) / max(1, len(sample_items))
        thumb_coverage = sum(1 for item in sample_items if item.get("thumbnail")) / max(1, len(sample_items))
        duration_coverage = sum(1 for item in sample_items if item.get("duration")) / max(1, len(sample_items))
        return ListingValidation(
            candidate_count=candidate_count,
            visible_candidate_count=visible_count,
            link_coverage=round(link_coverage, 3),
            title_coverage=round(title_coverage, 3),
            thumbnail_coverage=round(thumb_coverage, 3),
            duration_coverage=round(duration_coverage, 3),
            href_shapes=counter_top(href_shapes),
            sample_items=sample_items[:limit],
            errors=errors,
        )
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("listing validation failed")
        return ListingValidation(
            candidate_count=0,
            visible_candidate_count=0,
            link_coverage=0,
            title_coverage=0,
            thumbnail_coverage=0,
            duration_coverage=0,
            href_shapes=[],
            sample_items=[],
            errors=[str(exc)],
        )
    finally:
        context.close()


def convert_raw_links(raw_links: list[dict[str, Any]], base_url: str) -> list[LinkEvidence]:
    out: list[LinkEvidence] = []
    seen: set[str] = set()
    for raw in raw_links:
        abs_url = normalize_url(str(raw.get("href") or ""), base_url)
        if not abs_url or abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(LinkEvidence(
            href=str(raw.get("href") or ""),
            abs_url=abs_url,
            text=normalized_text(str(raw.get("text") or "")),
            selector=str(raw.get("selector") or ""),
            has_image=bool(raw.get("has_image")),
            classes=[str(c) for c in raw.get("classes", []) or []],
            href_shape=url_shape(abs_url),
        ))
    return out


def pick_selector_from_links(links_by_probe: list[list[LinkEvidence]]) -> str | None:
    selector_counts: Counter[str] = Counter()
    shape_counts: Counter[str] = Counter()
    for links in links_by_probe:
        for link in links:
            if link.selector and link.selector != "a":
                selector_counts[link.selector] += 1
            if link.href_shape:
                shape_counts[link.href_shape] += 1
    for selector, _ in selector_counts.most_common():
        if selector and selector != "a":
            return selector
    for shape, _ in shape_counts.most_common():
        first_segment = shape.strip("/").split("/", 1)[0]
        if first_segment and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", first_segment):
            return f'a[href*="/{first_segment}/"]'
    return None


def classify_detail_probe(probe: DetailProbe, media_type: str) -> None:
    useful_media = [
        row for row in [*probe.dom_media, *probe.network_media_after_load, *probe.network_media_after_click]
        if media_type_matches(str(row.get("url") or row.get("src") or ""), media_type)
           or (media_type == "all" and row.get("kind") in {"video", "audio", "image"})
    ]
    video_like_media = [
        row for row in [*probe.dom_media, *probe.network_media_after_load, *probe.network_media_after_click]
        if row.get("kind") in {"video", "audio"} or media_kind_from_url(str(row.get("url") or row.get("src") or "")) in {"video", "audio"}
    ]
    has_player = bool(probe.player_candidates or probe.iframe_candidates)
    has_episode_or_play_links = bool(probe.episode_links or probe.play_links)
    if media_type == "image":
        image_media = [
            row for row in [*probe.dom_media, *probe.network_media_after_load, *probe.network_media_after_click]
            if row.get("kind") == "image" or media_kind_from_url(str(row.get("url") or row.get("src") or "")) == "image"
        ]
        probe.page_kind = "gallery" if len(image_media) >= 2 else "unknown"
    elif useful_media or video_like_media or has_player:
        probe.page_kind = "playable_detail"
    elif has_episode_or_play_links:
        probe.page_kind = "intermediate"
    else:
        probe.page_kind = "unknown"


def probe_detail_page(
    runtime: BrowserRuntime,
    item: dict[str, str],
    rule: dict[str, Any],
    *,
    user_agent: str,
    timeout: float,
    click_play: bool,
    desktop: bool,
) -> DetailProbe:
    url = item.get("href") or item.get("url") or ""
    probe = DetailProbe(item_title=item.get("title", ""), item_url=url)
    context = runtime.new_context(user_agent=user_agent, desktop=desktop)
    page = context.new_page()
    network_after_load: list[dict[str, Any]] = []
    network_after_click: list[dict[str, Any]] = []
    current_sink = {"target": network_after_load}

    def on_response(response) -> None:
        try:
            response_url = response.url
            content_type = (response.headers.get("content-type") or "").lower()
            kind = media_kind_from_url(response_url)
            if kind == "unknown":
                if "mpegurl" in content_type or content_type.startswith("video/"):
                    kind = "video"
                elif content_type.startswith("audio/"):
                    kind = "audio"
                elif content_type.startswith("image/"):
                    kind = "image"
            if kind == "unknown":
                return
            current_sink["target"].append({
                "url": response_url,
                "kind": kind,
                "status": response.status,
                "content_type": content_type,
                "source": "network",
            })
        except Exception:  # noqa: BLE001
            return

    page.on("response", on_response)

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        page.wait_for_timeout(1000)
        raw = page.evaluate(DETAIL_EVIDENCE_JS)
        probe.final_url = str(raw.get("final_url") or page.url)
        probe.title = raw.get("title")
        probe.title_match_score = title_match_score(probe.item_title, probe.title)
        probe.title_in_page_title = probe.title_match_score >= 0.65
        probe.dom_media = normalize_dom_media(raw.get("media_nodes") or [], probe.final_url)
        probe.player_candidates = raw.get("player_nodes") or []
        probe.play_button_candidates = raw.get("play_buttons") or []
        probe.play_links = convert_raw_links(raw.get("play_links") or [], probe.final_url)
        probe.episode_links = convert_raw_links(raw.get("episode_links") or [], probe.final_url)
        probe.iframe_candidates = raw.get("iframes") or []
        probe.network_media_after_load = dedupe_media_rows(network_after_load, probe.final_url)

        selector_to_click = None
        if click_play:
            for button in probe.play_button_candidates[:5]:
                selector = str(button.get("selector") or "")
                if not selector:
                    continue
                try:
                    if page.locator(selector).count() > 0:
                        selector_to_click = selector
                        break
                except Exception:  # noqa: BLE001
                    continue
            if selector_to_click:
                current_sink["target"] = network_after_click
                try:
                    page.locator(selector_to_click).first.click(timeout=2500)
                    page.wait_for_timeout(2200)
                    probe.clicked_play_selector = selector_to_click
                except Exception as exc:  # noqa: BLE001
                    LOGGER.debug("click play failed selector=%s error=%s", selector_to_click, exc)
                probe.network_media_after_click = dedupe_media_rows(network_after_click, probe.final_url)

        all_link_groups = []
        if probe.episode_links:
            all_link_groups.append(probe.episode_links)
        if probe.play_links:
            all_link_groups.append(probe.play_links)
        probe.suggested_detail_selector = pick_selector_from_links(all_link_groups)
        probe.suggested_detail_mode = "expand" if any(len(group) > 1 for group in all_link_groups) else "single"
        classify_detail_probe(probe, str(rule.get("media_type") or "video"))
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("detail probe failed url=%s", url)
        probe.status = "error"
        probe.error = str(exc)
    finally:
        context.close()
    return probe


def normalize_dom_media(nodes: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in nodes:
        src = normalize_url(str(raw.get("src") or raw.get("poster") or ""), base_url)
        if not src:
            continue
        out.append({
            "url": src,
            "kind": media_kind_from_url(src),
            "tag": raw.get("tag"),
            "selector": raw.get("selector"),
            "poster": normalize_url(str(raw.get("poster") or ""), base_url) if raw.get("poster") else "",
            "source": "dom",
        })
    return out


def validate_hypothesis(
    runtime: BrowserRuntime,
    evidence: PageEvidence,
    hypothesis: RuleHypothesis,
    *,
    user_agent: str,
    timeout: float,
    validation_limit: int,
    detail_probes: int,
    click_play: bool,
    desktop: bool,
    progress_callback: Any | None = None,
) -> HypothesisValidation:
    rule = hypothesis.rule_draft
    if progress_callback:
        progress_callback(
            "validate-listing",
            0.05,
            f"Testing listing selector {rule.get('candidate_selector')}",
            {
                "candidate_selector": rule.get("candidate_selector"),
                "candidate_link_selector": rule.get("candidate_link_selector"),
                "validation_limit": validation_limit,
            },
        )
    listing_started = time.perf_counter()
    listing = validate_listing(
        runtime,
        evidence.final_url,
        rule,
        user_agent=user_agent,
        timeout=timeout,
        limit=validation_limit,
        desktop=desktop or bool(rule.get("force_desktop_mode")),
    )
    log_profile(
        "validate-listing",
        listing_started,
        hypothesis_id=hypothesis.id,
        candidate=rule.get("candidate_selector"),
        candidates=listing.candidate_count,
        visible=listing.visible_candidate_count,
        link_coverage=listing.link_coverage,
        title_coverage=listing.title_coverage,
        thumb_coverage=listing.thumbnail_coverage,
    )
    if progress_callback:
        progress_callback(
            "validate-listing",
            0.28,
            f"Listing selector matched {listing.visible_candidate_count}/{listing.candidate_count} visible candidates",
            {
                "candidate_count": listing.candidate_count,
                "visible_candidate_count": listing.visible_candidate_count,
                "link_coverage": listing.link_coverage,
                "title_coverage": listing.title_coverage,
                "thumbnail_coverage": listing.thumbnail_coverage,
                "duration_coverage": listing.duration_coverage,
                "sample_items": listing.sample_items[:5],
                "errors": listing.errors,
            },
        )
    probes: list[DetailProbe] = []
    probe_items = listing.sample_items[:detail_probes]
    for index, item in enumerate(probe_items, start=1):
        item_href = str(item.get("href") or "")
        if progress_callback:
            progress_callback(
                "validate-detail-probe",
                0.28 + 0.52 * ((index - 1) / max(1, len(probe_items))),
                (
                    f"Direct media probe {index}/{len(probe_items)}: {item.get('title') or item.get('href')}"
                    if media_type_matches(item_href, str(rule.get("media_type") or "video"))
                    else f"Opening detail probe {index}/{len(probe_items)}: {item.get('title') or item.get('href')}"
                ),
                {"index": index, "total": len(probe_items), "item": item},
            )
        probe_started = time.perf_counter()
        if media_type_matches(item_href, str(rule.get("media_type") or "video")):
            probe = DetailProbe(
                item_title=item.get("title", ""),
                item_url=item_href,
                final_url=item_href,
                page_kind="playable_detail",
                dom_media=[{"url": item_href, "kind": media_kind_from_url(item_href), "source": "listing-link"}],
            )
        else:
            probe = probe_detail_page(
                runtime,
                item,
                rule,
                user_agent=user_agent,
                timeout=timeout,
                click_play=click_play,
                desktop=desktop or bool(rule.get("force_desktop_mode")),
            )
        probes.append(probe)
        primary_count = len(probe_primary_media_rows(probe, str(rule.get("media_type") or "video")))
        log_profile(
            "validate-detail-probe",
            probe_started,
            hypothesis_id=hypothesis.id,
            index=index,
            item_url=item.get("href"),
            final_url=probe.final_url,
            status=probe.status,
            page_kind=probe.page_kind,
            primary_media_count=primary_count,
            dom_media=len(probe.dom_media),
            network_media=len(probe.network_media_after_load) + len(probe.network_media_after_click),
            episode_links=len(probe.episode_links),
            play_links=len(probe.play_links),
            error=probe.error,
        )
        if progress_callback:
            progress_callback(
                "validate-detail-probe",
                0.28 + 0.52 * (index / max(1, len(probe_items))),
                f"Detail probe {index}/{len(probe_items)} classified as {probe.page_kind}; media={primary_count}",
                {
                    "index": index,
                    "total": len(probe_items),
                    "item_url": item.get("href"),
                    "final_url": probe.final_url,
                    "status": probe.status,
                    "page_kind": probe.page_kind,
                    "primary_media_count": primary_count,
                    "dom_media_count": len(probe.dom_media),
                    "network_media_count": len(probe.network_media_after_load) + len(probe.network_media_after_click),
                    "episode_link_count": len(probe.episode_links),
                    "play_link_count": len(probe.play_links),
                    "error": probe.error,
                },
            )

    if progress_callback:
        progress_callback("score-validation", 0.84, "Scoring validation and suggested repairs", {"detail_probe_count": len(probes)})
    repairs = suggest_repairs_from_probes(rule, probes)
    quality = score_validation(listing, probes, rule, repairs)
    warnings = []
    if listing.candidate_count == 0:
        warnings.append("candidate_selector matched zero nodes")
    if listing.link_coverage < 0.5:
        warnings.append("candidate links have weak coverage")
    if probes and not any(p.page_kind in {"playable_detail", "gallery", "intermediate"} for p in probes):
        warnings.append("detail probes did not identify playable media or intermediate links")
    if progress_callback:
        progress_callback(
            "score-validation",
            0.95,
            f"Validation score {quality:.3f}; repairs={json.dumps(repairs, ensure_ascii=False)}",
            {"quality_score": quality, "repairs": repairs, "warnings": warnings},
        )
    return HypothesisValidation(
        hypothesis_id=hypothesis.id,
        listing=listing,
        detail_probes=probes,
        quality_score=quality,
        suggested_repairs=repairs,
        warnings=warnings,
    )


DETAIL_HOP_POLICY_KEYS = (
    "detail_url_selector",
    "detail_url_mode",
    "detail_url_selector_2",
    "detail_url_mode_2",
    "detail_url_selector_3",
    "detail_url_mode_3",
    "detail_url_max_hops",
    "detail_url_stop_when_media_found",
    "max_detail_concurrency",
)


def probe_primary_media_rows(probe: DetailProbe, media_type: str) -> list[dict[str, Any]]:
    """Return media rows that should count as primary media on a detail page.

    For video pages, poster/thumbnail images do not count. A detail page with
    direct video/audio DOM or network media is already a playable detail page and
    should not receive a single extra hop.
    """
    normalized_type = normalize_media_type(media_type)
    rows = [*probe.dom_media, *probe.network_media_after_load, *probe.network_media_after_click]
    primary: list[dict[str, Any]] = []
    for row in rows:
        url = str(row.get("url") or row.get("src") or "")
        kind = str(row.get("kind") or media_kind_from_url(url) or "unknown")
        if normalized_type == "video":
            if kind in {"video", "audio"} or media_kind_from_url(url) in {"video", "audio"}:
                primary.append(row)
        elif normalized_type == "audio":
            if kind == "audio" or media_kind_from_url(url) == "audio":
                primary.append(row)
        elif normalized_type == "image":
            if kind == "image" or media_kind_from_url(url) == "image":
                primary.append(row)
        elif normalized_type == "all":
            if kind in {"video", "audio", "image"} or media_kind_from_url(url) in {"video", "audio", "image"}:
                primary.append(row)
    return primary


def probe_has_primary_media(probe: DetailProbe, media_type: str) -> bool:
    return bool(probe_primary_media_rows(probe, media_type))


def detail_hop_repair_from_probes(probes: list[DetailProbe], media_type: str) -> dict[str, Any]:
    """Decide whether a detail hop is actually needed.

    Policy:
    1. Detail pages with no primary media need a hop when stable play/episode links exist.
    2. Detail pages with primary media do not need a single hop.
    3. Detail pages with primary media may still need an expand hop when episode/part links exist.
    """
    link_groups: list[list[LinkEvidence]] = []
    force_expand = False
    no_media_with_links = 0
    media_with_episode_links = 0
    media_without_episode_links = 0

    for probe in probes:
        has_media = probe_has_primary_media(probe, media_type)
        episode_links = probe.episode_links
        play_links = probe.play_links

        if has_media:
            if episode_links:
                # Playable detail page with a real episode/part list: expand from this page.
                link_groups.append(episode_links)
                force_expand = True
                media_with_episode_links += 1
            else:
                # Already playable and no episode list: candidate_link_selector has reached the final page.
                media_without_episode_links += 1
            continue

        # No primary media: this is an intermediate page only if it exposes a next link.
        if episode_links:
            link_groups.append(episode_links)
            no_media_with_links += 1
            force_expand = True
        elif play_links:
            link_groups.append(play_links)
            no_media_with_links += 1
            if len(play_links) > 1:
                force_expand = True

    if not link_groups:
        return {}

    # Avoid adding a hop because of incidental play links when most sampled pages
    # already have primary media and no episode list. In that case a single hop is harmful.
    if no_media_with_links == 0 and media_with_episode_links == 0:
        return {}
    if media_without_episode_links > 0 and no_media_with_links > 0 and no_media_with_links < media_without_episode_links:
        return {}

    selector = pick_selector_from_links(link_groups)
    if not selector:
        return {}
    return {
        "detail_url_selector": selector,
        "detail_url_mode": "expand" if force_expand or any(len(group) > 1 for group in link_groups) else "single",
        "detail_url_max_hops": 3,
        "detail_url_stop_when_media_found": False,
    }


def remove_detail_hop_fields(rule: dict[str, Any]) -> dict[str, Any]:
    patched = dict(rule)
    for key in DETAIL_HOP_POLICY_KEYS:
        patched.pop(key, None)
    return patched


def enforce_detail_hop_policy(
    rule: dict[str, Any],
    validation: HypothesisValidation | None,
    source_url: str,
    max_items: int,
) -> dict[str, Any]:
    """Force final rules to follow the verified detail-hop policy."""
    patched = dict(rule)
    if validation is None:
        return sanitize_rule(patched, source_url, max_items)

    hop_repair = detail_hop_repair_from_probes(validation.detail_probes, str(patched.get("media_type") or "video"))
    if hop_repair:
        for key, value in hop_repair.items():
            patched[key] = value
    else:
        patched = remove_detail_hop_fields(patched)
    return sanitize_rule(patched, source_url, max_items)


def suggest_repairs_from_probes(rule: dict[str, Any], probes: list[DetailProbe]) -> dict[str, Any]:
    repairs: dict[str, Any] = {}
    media_type = str(rule.get("media_type") or "video")
    repairs.update(detail_hop_repair_from_probes(probes, media_type))

    media_seen_by_network = [
        row
        for p in probes
        for row in [*p.network_media_after_load, *p.network_media_after_click]
        if media_type_matches(str(row.get("url") or ""), media_type)
           or (media_type == "video" and row.get("kind") == "video")
    ]
    if media_seen_by_network:
        repairs["force_network_sniff"] = True
        repairs["network_sniff_timeout"] = max(5.0, safe_float(rule.get("network_sniff_timeout"), 5.0))
        repairs["network_sniff_idle_timeout"] = max(1.0, safe_float(rule.get("network_sniff_idle_timeout"), 1.0))

    if media_type == "video":
        repairs["media_type"] = "video"
    return repairs

def score_validation(
    listing: ListingValidation,
    probes: list[DetailProbe],
    rule: dict[str, Any],
    repairs: dict[str, Any],
) -> float:
    score = 0.0
    score += clamp(listing.visible_candidate_count / 12, 0, 1) * 0.20
    score += listing.link_coverage * 0.25
    score += listing.title_coverage * 0.10
    score += listing.thumbnail_coverage * 0.10
    if probes:
        playable = sum(1 for p in probes if p.page_kind in {"playable_detail", "gallery"})
        intermediate = sum(1 for p in probes if p.page_kind == "intermediate")
        media_hits = sum(1 for p in probes if p.dom_media or p.network_media_after_load or p.network_media_after_click)
        title_probe_score = sum(p.title_match_score for p in probes) / max(1, len(probes))
        score += clamp((playable + intermediate) / len(probes), 0, 1) * 0.20
        score += clamp(media_hits / len(probes), 0, 1) * 0.15
        score += clamp(title_probe_score, 0, 1) * 0.08
    if listing.errors:
        score -= 0.15
    if repairs.get("force_network_sniff"):
        score += 0.05
    return round(clamp(score, 0, 1), 3)


def apply_repairs(rule: dict[str, Any], repairs: dict[str, Any], source_url: str, max_items: int) -> dict[str, Any]:
    merged = dict(rule)
    for key, value in repairs.items():
        if key in SUPPORTED_RULE_KEYS and value not in (None, ""):
            merged[key] = value
    return sanitize_rule(merged, source_url, max_items)


def local_finalize(
    evidence: PageEvidence,
    hypotheses: list[RuleHypothesis],
    validations: list[HypothesisValidation],
    max_items: int,
) -> tuple[dict[str, Any], str, str, list[str]]:
    if not validations:
        fallback = local_hypotheses(evidence, max_items, limit=1)[0].rule_draft
        return fallback, "heuristic", "Generated by local fallback; no validations were available.", []
    best = max(validations, key=lambda v: v.quality_score)
    hypothesis = next((h for h in hypotheses if h.id == best.hypothesis_id), hypotheses[0])
    rule = apply_repairs(hypothesis.rule_draft, best.suggested_repairs, evidence.final_url, max_items)
    rule = enforce_detail_hop_policy(rule, best, evidence.final_url, max_items)

    examples: list[str] = []
    has_detail_hop = any(key in rule for key in ("detail_url_selector", "detail_url_selector_2", "detail_url_selector_3"))
    for probe in best.detail_probes:
        if has_detail_hop and probe.suggested_detail_selector:
            source_links = probe.episode_links or probe.play_links
            examples.extend(link.abs_url for link in source_links[:3])
        else:
            examples.append(probe.final_url or probe.item_url)

    reasoning = (
        f"Selected {hypothesis.id} by validation score {best.quality_score}. "
        f"Listing matched {best.listing.visible_candidate_count} visible candidates with "
        f"link coverage {best.listing.link_coverage}. "
        f"Detail probes classified pages as "
        f"{Counter(p.page_kind for p in best.detail_probes).most_common()}."
    )
    return rule, str(best.quality_score), reasoning, examples[:8]


def ai_finalize_or_none(
    evidence: PageEvidence,
    hypotheses: list[RuleHypothesis],
    validations: list[HypothesisValidation],
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str, str, list[str]] | None:
    if args.no_ai or not args.api_key:
        return None
    messages = build_final_prompt(evidence, hypotheses, validations, args.max_items)
    try:
        result = call_chat_completion(
            messages,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
            timeout=args.timeout,
            use_response_format=not args.no_response_format,
        )
    except urllib.error.HTTPError:
        if args.no_response_format:
            LOGGER.exception("AI final request failed")
            return None
        try:
            result = call_chat_completion(
                messages,
                api_key=args.api_key,
                base_url=args.base_url,
                model=args.model,
                timeout=args.timeout,
                use_response_format=False,
            )
        except Exception:  # noqa: BLE001
            LOGGER.exception("AI final retry failed")
            return None
    except Exception:  # noqa: BLE001
        LOGGER.exception("AI final request failed")
        return None

    raw_rule = result.get("rule") if isinstance(result.get("rule"), dict) else result
    rule = sanitize_rule(raw_rule, evidence.final_url, args.max_items)
    best_validation = max(validations, key=lambda v: v.quality_score) if validations else None
    rule = enforce_detail_hop_policy(rule, best_validation, evidence.final_url, args.max_items)
    confidence = one_line(result.get("confidence", "ai-finalized"))
    reasoning = one_line(result.get("reasoning", "Generated by AI finalizer from validation results."))
    examples = result.get("detail_url_examples")
    detail_url_examples = [str(v) for v in examples if v] if isinstance(examples, list) else []
    return rule, confidence, reasoning, detail_url_examples


def sanitize_rule(raw_rule: dict[str, Any], source_url: str, max_items: int) -> dict[str, Any]:
    rule: dict[str, Any] = {}
    for key in SUPPORTED_RULE_KEYS:
        value = raw_rule.get(key) if isinstance(raw_rule, dict) else None
        if value not in (None, ""):
            rule[key] = value

    rule["source"] = str(rule.get("source") or source_url)
    if not re.match(r"^https?://", rule["source"], re.I):
        rule["source"] = source_url

    candidate = str(rule.get("candidate_selector") or "a:has(img)").strip()
    rule["candidate_selector"] = candidate or "a:has(img)"

    string_keys = (
        "candidate_link_selector", "detail_url_selector", "detail_url_mode",
        "detail_url_selector_2", "detail_url_mode_2", "detail_url_selector_3",
        "detail_url_mode_3", "title_selector", "thumbnail_selector",
        "duration_selector", "media_type", "media_delivery",
    )
    for key in string_keys:
        if key in rule:
            rule[key] = str(rule[key]).strip()
            if not rule[key]:
                rule.pop(key, None)

    rule["media_type"] = normalize_media_type(rule.get("media_type"))

    media_delivery = str(rule.get("media_delivery") or "redirect").strip().lower()
    media_delivery = {"302": "redirect", "direct": "redirect"}.get(media_delivery, media_delivery)
    rule["media_delivery"] = media_delivery if media_delivery in {"auto", "proxy", "redirect"} else "redirect"

    try:
        media_url_ttl = float(rule["media_url_ttl"]) if "media_url_ttl" in rule else None
    except (TypeError, ValueError):
        media_url_ttl = None
    if media_url_ttl is None:
        rule.pop("media_url_ttl", None)
    else:
        rule["media_url_ttl"] = max(0.0, media_url_ttl)

    has_detail = any(key in rule for key in ("detail_url_selector", "detail_url_selector_2", "detail_url_selector_3"))
    if has_detail:
        for mode_key in ("detail_url_mode", "detail_url_mode_2", "detail_url_mode_3"):
            if mode_key in rule:
                mode = str(rule[mode_key]).strip().lower()
                rule[mode_key] = mode if mode in {"single", "expand"} else "single"
        rule["detail_url_max_hops"] = max(1, min(int(safe_float(rule.get("detail_url_max_hops"), 3)), 10))
        rule["max_detail_concurrency"] = max(1, min(int(safe_float(rule.get("max_detail_concurrency"), 4)), 16))
        stop_when_media = rule.get("detail_url_stop_when_media_found", False)
        if isinstance(stop_when_media, str):
            stop_when_media = stop_when_media.strip().lower() in {"true", "1", "yes", "on"}
        rule["detail_url_stop_when_media_found"] = bool(stop_when_media)
    else:
        for key in ("detail_url_max_hops", "max_detail_concurrency", "detail_url_stop_when_media_found"):
            rule.pop(key, None)

    projection = str(rule.get("projection") or "by-item").strip()
    rule["projection"] = projection if projection in {"by-item", "flat"} else "by-item"

    rule["max_items"] = max(1, min(int(safe_float(rule.get("max_items"), max_items)), 500))

    for bool_key in ("force_network_sniff", "force_desktop_mode"):
        value = rule.get(bool_key, False)
        if isinstance(value, str):
            value = value.strip().lower() in {"true", "1", "yes", "on"}
        rule[bool_key] = bool(value)
    # v3: fast_mode is always enabled, regardless of AI/user input.
    rule["fast_mode"] = True
    # v3: these fields are intentionally disabled and must never be emitted.
    rule.pop("media_selector", None)
    rule.pop("play_button_selector", None)

    rule["selector_wait_timeout"] = max(0.0, safe_float(rule.get("selector_wait_timeout"), 0.0))
    for timeout_key, default in (("network_sniff_timeout", 5.0), ("network_sniff_idle_timeout", 1.0)):
        if timeout_key in rule:
            rule[timeout_key] = max(0.0, safe_float(rule.get(timeout_key), default))

    # Prevent dangerous/generic next-hop selectors.
    for key in ("detail_url_selector", "detail_url_selector_2", "detail_url_selector_3"):
        if str(rule.get(key) or "").strip() == "a":
            rule.pop(key, None)

    return {key: rule[key] for key in SUPPORTED_RULE_KEYS if key in rule}


def parse_rule_text(text: str, source_url: str, max_items: int) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        elif "source" not in values:
            key, value = "source", line
        else:
            continue
        values[key.strip().lower()] = value.strip()
    return sanitize_rule(values, source_url or str(values.get("source") or ""), max_items)


def parse_detail_hops(rule: dict[str, Any]) -> list[tuple[str, str]]:
    hops: list[tuple[str, str]] = []
    for index in range(1, 11):
        selector_key = "detail_url_selector" if index == 1 else f"detail_url_selector_{index}"
        mode_key = "detail_url_mode" if index == 1 else f"detail_url_mode_{index}"
        selector = str(rule.get(selector_key, "")).strip()
        if not selector:
            if index == 1:
                continue
            break
        mode = str(rule.get(mode_key, "single")).strip().lower()
        hops.append((selector, mode if mode in {"single", "expand"} else "single"))
    return hops


def render_rule(
    rule: dict[str, Any],
    *,
    confidence: str | None = None,
    reasoning: str | None = None,
    detail_url_examples: list[str] | None = None,
) -> str:
    lines = [
        "# Web Media Projection Resolver rule",
        f"# Generated at {now_string()}",
        f"# Source page: {rule.get('source', '<unknown>')}",
    ]
    if confidence:
        lines.append(f"# Confidence: {one_line(confidence)}")
    if reasoning:
        wrapped = textwrap.wrap(one_line(reasoning), width=100)
        lines.extend(f"# Reasoning: {line}" if i == 0 else f"#   {line}" for i, line in enumerate(wrapped))
    if detail_url_examples:
        lines.append("# Detail URL examples:")
        lines.extend(f"# - {example}" for example in detail_url_examples[:8])
    lines.append("")
    for key in SUPPORTED_RULE_KEYS:
        if key not in rule:
            continue
        value = rule[key]
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def json_output(result: InferenceResult) -> dict[str, Any]:
    return {
        "used_ai": result.used_ai,
        "rule": result.rule,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "detail_url_examples": result.detail_url_examples,
        "evidence": {
            "requested_url": result.evidence.requested_url,
            "final_url": result.evidence.final_url,
            "title": result.evidence.title,
            "candidate_groups": compact_candidate_groups(result.evidence.candidate_groups),
            "network_media_after_load": result.evidence.network_media_after_load[:20],
            "lazy_load_observed": result.evidence.lazy_load_observed,
        },
        "hypotheses": [to_plain(h) for h in result.hypotheses],
        "validations": [compact_validation(v) for v in result.validations],
    }


def emit_progress(args: argparse.Namespace, phase: str, fraction: float, message: str, data: dict[str, Any] | None = None) -> None:
    callback = getattr(args, "progress_callback", None)
    payload = data or {}
    LOGGER.info("PROGRESS phase=%s fraction=%.3f message=%s data=%s", phase, clamp(fraction, 0.0, 1.0), message, json.dumps(payload, ensure_ascii=False, default=str))
    print(
        f"PROGRESS phase={phase} fraction={clamp(fraction, 0.0, 1.0):.3f} message={message} data={json.dumps(payload, ensure_ascii=False, default=str)}",
        file=sys.stderr,
    )
    if callback:
        callback(phase, clamp(fraction, 0.0, 1.0), message, payload)


def log_profile(phase: str, started_at: float, **data: Any) -> None:
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)
    payload = json.dumps(data, ensure_ascii=False, default=str)
    LOGGER.info("PROFILE phase=%s duration_ms=%s data=%s", phase, duration_ms, payload)
    print(f"PROFILE phase={phase} duration_ms={duration_ms} data={payload}", file=sys.stderr)


def run_generation(args: argparse.Namespace) -> InferenceResult:
    total_started = time.perf_counter()
    emit_progress(args, "browser-start", 0.02, "Starting v3 browser runtime", {})
    runtime = BrowserRuntime(configured_proxy_url(), headless=not args.headful)
    try:
        evidence_started = time.perf_counter()
        emit_progress(args, "collect-evidence", 0.05, "Loading source page and collecting listing evidence", {"url": args.url})
        evidence = collect_page_evidence(
            runtime,
            args.url,
            user_agent=args.user_agent,
            timeout=args.timeout,
            max_groups=args.max_candidate_groups,
            max_samples=args.sample_items,
            scroll_steps=args.scroll_steps,
            desktop=args.desktop,
        )
        log_profile(
            "collect-evidence",
            evidence_started,
            final_url=evidence.final_url,
            groups=len(evidence.candidate_groups),
            network_media=len(evidence.network_media_after_load),
            lazy_load_observed=evidence.lazy_load_observed,
        )
        emit_progress(
            args,
            "collect-evidence",
            0.2,
            f"Collected {len(evidence.candidate_groups)} candidate groups from rendered page",
            {
                "final_url": evidence.final_url,
                "groups": len(evidence.candidate_groups),
                "network_media": len(evidence.network_media_after_load),
                "lazy_load_observed": evidence.lazy_load_observed,
            },
        )

        local_started = time.perf_counter()
        local_h = local_hypotheses(evidence, args.max_items, limit=args.max_candidate_groups)
        log_profile("local-hypotheses", local_started, count=len(local_h))
        emit_progress(args, "local-hypotheses", 0.26, f"Prepared {len(local_h)} local rule hypotheses", {"count": len(local_h)})

        ai_started = time.perf_counter()
        emit_progress(args, "ai-hypotheses", 0.3, "Requesting AI rule hypotheses" if not args.no_ai and args.api_key else "Skipping AI hypotheses; using local analysis", {})
        ai_h = ai_hypotheses_or_empty(evidence, args)
        log_profile("ai-hypotheses", ai_started, count=len(ai_h), enabled=not args.no_ai and bool(args.api_key))
        emit_progress(args, "ai-hypotheses", 0.4, f"Prepared {len(ai_h)} AI hypotheses", {"count": len(ai_h)})

        hypotheses = merge_hypotheses(ai_h, local_h)
        LOGGER.info("hypotheses prepared ai=%d local=%d merged=%d", len(ai_h), len(local_h), len(hypotheses))
        emit_progress(
            args,
            "merge-hypotheses",
            0.43,
            f"Merged {len(hypotheses)} hypotheses for validation",
            {"ai": len(ai_h), "local": len(local_h), "merged": len(hypotheses)},
        )

        validations: list[HypothesisValidation] = []
        validation_targets = hypotheses[:args.validate_hypotheses]
        for index, hypothesis in enumerate(validation_targets, start=1):
            LOGGER.info("validate hypothesis id=%s candidate=%s", hypothesis.id, hypothesis.rule_draft.get("candidate_selector"))
            candidate = str(hypothesis.rule_draft.get("candidate_selector") or "")
            emit_progress(
                args,
                "validate-hypothesis",
                0.45 + 0.3 * ((index - 1) / max(1, len(validation_targets))),
                f"Validating {hypothesis.id}: {candidate}",
                {
                    "index": index,
                    "total": len(validation_targets),
                    "hypothesis_id": hypothesis.id,
                    "source": hypothesis.source,
                    "candidate_selector": candidate,
                    "candidate_link_selector": hypothesis.rule_draft.get("candidate_link_selector"),
                    "detail_probes": args.detail_probes,
                },
            )
            validation_started = time.perf_counter()
            validation = validate_hypothesis(
                runtime,
                evidence,
                hypothesis,
                user_agent=args.user_agent,
                timeout=args.timeout,
                validation_limit=args.validation_limit,
                detail_probes=args.detail_probes,
                click_play=ENABLE_CLICK_PLAY_PROBE and not args.no_click_play,
                desktop=args.desktop,
                progress_callback=lambda phase, local_fraction, message, data, h=hypothesis, i=index: emit_progress(
                    args,
                    phase,
                    0.45 + 0.3 * (((i - 1) + local_fraction) / max(1, len(validation_targets))),
                    message,
                    {"hypothesis_id": h.id, **(data or {})},
                ),
            )
            validations.append(validation)
            log_profile(
                "validate-hypothesis",
                validation_started,
                hypothesis_id=hypothesis.id,
                source=hypothesis.source,
                candidate=candidate,
                score=validation.quality_score,
                metrics=validation_metrics_line(validation),
                repairs=validation.suggested_repairs,
                warnings=validation.warnings,
            )
            emit_progress(
                args,
                "validated-hypothesis",
                0.45 + 0.3 * (index / max(1, len(validation_targets))),
                f"Validated {hypothesis.id}: {validation_metrics_line(validation)}",
                {
                    "hypothesis_id": hypothesis.id,
                    "source": hypothesis.source,
                    "candidate_selector": candidate,
                    "quality_score": validation.quality_score,
                    "metrics": validation_metrics_line(validation),
                    "repairs": validation.suggested_repairs,
                    "warnings": validation.warnings,
                },
            )
            print_validation_result(hypothesis, validation)

        final_started = time.perf_counter()
        emit_progress(args, "finalize-rule", 0.78, "Selecting final rule from validated hypotheses", {"validations": len(validations)})
        ai_final = ai_finalize_or_none(evidence, hypotheses, validations, args)
        if ai_final is not None:
            rule, confidence, reasoning, examples = ai_final
            used_ai = True
            finalizer = "ai"
        else:
            rule, confidence, reasoning, examples = local_finalize(evidence, hypotheses, validations, args.max_items)
            used_ai = False if args.no_ai or not args.api_key else any(h.source == "ai" for h in hypotheses)
            finalizer = "local"
        best_validation = max(validations, key=lambda item: item.quality_score) if validations else None
        log_profile(
            "finalize-rule",
            final_started,
            finalizer=finalizer,
            confidence=confidence,
            best_hypothesis=best_validation.hypothesis_id if best_validation else None,
            best_score=best_validation.quality_score if best_validation else None,
        )
        emit_progress(
            args,
            "finalize-rule",
            0.84,
            f"Selected {best_validation.hypothesis_id if best_validation else finalizer} using {finalizer} finalizer",
            {
                "finalizer": finalizer,
                "confidence": confidence,
                "best_hypothesis": best_validation.hypothesis_id if best_validation else None,
                "best_score": best_validation.quality_score if best_validation else None,
                "reasoning": reasoning,
            },
        )

        sanitize_started = time.perf_counter()
        final_rule = prefer_scoped_candidate_selector(sanitize_rule(rule, evidence.final_url, args.max_items), evidence, args.max_items)
        log_profile("sanitize-final-rule", sanitize_started, keys=sorted(final_rule.keys()))
        emit_progress(args, "rule-ready", 0.88, "Final rule is ready; executing preview", {"rule": final_rule})
        log_profile("generate-total", total_started, finalizer=finalizer, used_ai=used_ai)
        return InferenceResult(
            rule=final_rule,
            used_ai=used_ai,
            confidence=confidence,
            reasoning=reasoning,
            detail_url_examples=examples,
            evidence=evidence,
            hypotheses=hypotheses,
            validations=validations,
        )
    finally:
        runtime.close()


def debug_rule(args: argparse.Namespace) -> tuple[list[dict[str, str]], list[DebugEvent], list[str], dict[str, Any]]:
    with open(args.rule_file, "r", encoding="utf-8") as file:
        rule = parse_rule_text(file.read(), "", max_items=500)
    runtime = BrowserRuntime(configured_proxy_url(), headless=not args.headful)
    events: list[DebugEvent] = []
    diagnoses: list[str] = []
    items: list[dict[str, str]] = []
    try:
        listing = validate_listing(
            runtime,
            str(rule.get("source") or ""),
            rule,
            user_agent=args.user_agent,
            timeout=args.timeout,
            limit=args.limit,
            desktop=bool(rule.get("force_desktop_mode")) or args.desktop,
        )
        events.append(DebugEvent(
            kind="candidate_scan",
            message=f"候选项匹配 {listing.candidate_count} 个，可见 {listing.visible_candidate_count} 个",
            level="success" if listing.candidate_count else "error",
            data=to_plain(listing),
        ))
        if listing.errors:
            diagnoses.extend(listing.errors)
        if not listing.sample_items:
            diagnoses.append("candidate_selector 或 candidate_link_selector 没有解析出可访问 item URL。")
            return items, events, diagnoses, rule

        hops = parse_detail_hops(rule)
        events.append(DebugEvent(
            kind="detail_hops",
            message=f"启用了 {len(hops)} 段 detail 跳转" if hops else "无 detail 跳转",
            level="info",
            data={"hops": [{"selector": selector, "mode": mode} for selector, mode in hops]},
        ))

        for sample in listing.sample_items[:args.limit]:
            current_items = [{"href": sample["href"], "title": sample.get("title") or sample["href"]}]
            for hop_index, (selector, mode) in enumerate(hops, start=1):
                next_items: list[dict[str, str]] = []
                for current in current_items:
                    expanded = debug_expand_once(
                        runtime,
                        current["href"],
                        selector,
                        mode,
                        user_agent=args.user_agent,
                        timeout=args.timeout,
                        desktop=bool(rule.get("force_desktop_mode")) or args.desktop,
                    )
                    events.append(DebugEvent(
                        kind="hop_selector_result",
                        message=f"第 {hop_index} 跳 selector 命中 {len(expanded)} 个链接",
                        level="success" if expanded else "error",
                        data={"page_url": current["href"], "selector": selector, "mode": mode, "examples": expanded[:5]},
                    ))
                    if not expanded:
                        diagnoses.append(f"第 {hop_index} 跳 selector={selector} 在 {current['href']} 没有命中。")
                        next_items.append(current)
                    else:
                        for idx, link in enumerate(expanded if mode == "expand" else expanded[:1], start=1):
                            title = current["title"]
                            if mode == "expand":
                                title = f"{title} - {link.get('text') or f'Part {idx}'}"
                            next_items.append({"href": link["href"], "title": title})
                current_items = next_items
            items.extend({"title": item["title"], "url": item["href"]} for item in current_items)

        if not diagnoses:
            diagnoses.append("当前 rule 的候选项和跳转链解析正常。若实际播放失败，应检查 network sniff 或详情页媒体识别。")
        return items, events, diagnoses, rule
    finally:
        runtime.close()


def debug_expand_once(
    runtime: BrowserRuntime,
    url: str,
    selector: str,
    mode: str,
    *,
    user_agent: str,
    timeout: float,
    desktop: bool,
) -> list[dict[str, str]]:
    context = runtime.new_context(user_agent=user_agent, desktop=desktop)
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
        page.wait_for_timeout(800)
        rows = page.evaluate(
            """({ selector }) => Array.from(document.querySelectorAll(selector)).map((node) => ({
                href: node.getAttribute('href') || node.getAttribute('data-href') || node.getAttribute('data-url') || node.getAttribute('data-play-url') || node.getAttribute('data-src') || '',
                text: (node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim(),
            })).filter(row => row.href)""",
            {"selector": selector},
        )
        output = []
        seen = set()
        for row in rows:
            href = normalize_url(row.get("href", ""), page.url)
            if not href or href in seen:
                continue
            seen.add(href)
            output.append({"href": href, "text": row.get("text", "")})
        return output if mode == "expand" else output[:1]
    finally:
        context.close()


def render_debug_report(rule: dict[str, Any], items: list[dict[str, str]], events: list[DebugEvent], diagnoses: list[str]) -> str:
    lines: list[str] = []
    lines.append(colorize("Web Media Debug", Ansi.bold, Ansi.cyan))
    lines.append(f"{colorize('Source', Ansi.bold)}: {rule.get('source', '<unknown>')}")
    lines.append(f"{colorize('Candidate', Ansi.bold)}: {rule.get('candidate_selector')} | link={rule.get('candidate_link_selector') or '<default>'}")
    lines.append("")
    for event in events:
        icon = {
            "success": colorize("OK", Ansi.green, Ansi.bold),
            "error": colorize("FAIL", Ansi.red, Ansi.bold),
            "warning": colorize("WARN", Ansi.yellow, Ansi.bold),
        }.get(event.level, colorize("INFO", Ansi.blue, Ansi.bold))
        lines.append(f"{icon} {event.message}")
        if event.kind == "candidate_scan":
            lines.append(f"    link_coverage={event.data.get('link_coverage')} title_coverage={event.data.get('title_coverage')} thumb_coverage={event.data.get('thumbnail_coverage')}")
            for sample in event.data.get("sample_items", [])[:3]:
                lines.append(f"    sample: {sample.get('title', '')} -> {sample.get('href', '')}")
        elif event.kind == "hop_selector_result":
            lines.append(f"    selector={event.data.get('selector')} mode={event.data.get('mode')}")
            for sample in event.data.get("examples", [])[:3]:
                lines.append(f"    link: {sample.get('text', '')} -> {sample.get('href', '')}")
    lines.append("")
    lines.append(colorize("Diagnoses", Ansi.bold, Ansi.yellow))
    for diagnosis in diagnoses:
        lines.append(f"- {diagnosis}")
    lines.append("")
    lines.append(colorize("Final Item URLs", Ansi.bold, Ansi.green))
    for item in items[:50]:
        lines.append(f"- {item['title']} -> {item['url']}")
    if len(items) > 50:
        lines.append(f"... {len(items) - 50} more")
    return "\n".join(lines) + "\n"




def pct(value: float) -> str:
    return f"{clamp(value, 0, 1) * 100:.0f}%"


def validation_metrics_line(validation: HypothesisValidation) -> str:
    listing = validation.listing
    probe_count = len(validation.detail_probes)
    title_probe_score = (
        sum(p.title_match_score for p in validation.detail_probes) / max(1, probe_count)
        if probe_count else 0.0
    )
    media_hits = sum(
        1 for p in validation.detail_probes
        if p.dom_media or p.network_media_after_load or p.network_media_after_click
    )
    kinds = ", ".join(
        f"{kind}:{count}" for kind, count in Counter(p.page_kind for p in validation.detail_probes).most_common()
    ) or "none"
    return (
        f"score={validation.quality_score:.3f} "
        f"candidates={listing.visible_candidate_count}/{listing.candidate_count} "
        f"link={pct(listing.link_coverage)} "
        f"title={pct(listing.title_coverage)} "
        f"thumb={pct(listing.thumbnail_coverage)} "
        f"duration={pct(listing.duration_coverage)} "
        f"detail={probe_count} "
        f"media_hits={media_hits} "
        f"title_page_match={pct(title_probe_score)} "
        f"kinds={kinds}"
    )


def print_validation_result(hypothesis: RuleHypothesis, validation: HypothesisValidation) -> None:
    score_style = Ansi.green if validation.quality_score >= 0.75 else Ansi.yellow if validation.quality_score >= 0.45 else Ansi.red
    print(
        colorize("VALIDATED", Ansi.bold, score_style),
        colorize(hypothesis.id, Ansi.bold),
        f"source={hypothesis.source}",
        f"candidate={hypothesis.rule_draft.get('candidate_selector')}",
        file=sys.stderr,
    )
    print("  " + validation_metrics_line(validation), file=sys.stderr)
    if validation.suggested_repairs:
        print("  " + colorize("repairs", Ansi.cyan) + f": {json.dumps(validation.suggested_repairs, ensure_ascii=False)}", file=sys.stderr)
    if validation.warnings:
        print("  " + colorize("warnings", Ansi.yellow) + f": {'; '.join(validation.warnings)}", file=sys.stderr)
    sample_titles = [item.get("title", "") for item in validation.listing.sample_items[:3] if item.get("title")]
    if sample_titles:
        print("  samples: " + " | ".join(sample_titles), file=sys.stderr)


def render_generation_report(result: InferenceResult) -> str:
    lines: list[str] = []
    lines.append(colorize("Web Media Rule Generation", Ansi.bold, Ansi.cyan))
    lines.append(f"{colorize('Source', Ansi.bold)}: {result.evidence.final_url}")
    lines.append(f"{colorize('Selected confidence', Ansi.bold)}: {result.confidence}")
    lines.append(f"{colorize('Candidate', Ansi.bold)}: {result.rule.get('candidate_selector')} | link={result.rule.get('candidate_link_selector') or '<default>'}")
    lines.append(f"{colorize('Title selector', Ansi.bold)}: {result.rule.get('title_selector') or '<none>'}")
    lines.append(f"{colorize('Media', Ansi.bold)}: type={result.rule.get('media_type')} sniff={result.rule.get('force_network_sniff')} fast_mode={result.rule.get('fast_mode')}")
    if result.reasoning:
        lines.append(f"{colorize('Reasoning', Ansi.bold)}: {result.reasoning}")
    lines.append("")
    lines.append(colorize("Hypothesis validation", Ansi.bold, Ansi.magenta if hasattr(Ansi, 'magenta') else Ansi.cyan))
    h_by_id = {h.id: h for h in result.hypotheses}
    for validation in sorted(result.validations, key=lambda v: v.quality_score, reverse=True):
        h = h_by_id.get(validation.hypothesis_id)
        prefix = f"{validation.hypothesis_id}"
        source = f"{h.source}" if h else "?"
        candidate = h.rule_draft.get("candidate_selector") if h else "?"
        score_style = Ansi.green if validation.quality_score >= 0.75 else Ansi.yellow if validation.quality_score >= 0.45 else Ansi.red
        lines.append(f"{colorize(prefix, Ansi.bold, score_style)} [{source}] {candidate}")
        lines.append(f"  {validation_metrics_line(validation)}")
        if validation.suggested_repairs:
            lines.append(f"  repairs: {json.dumps(validation.suggested_repairs, ensure_ascii=False)}")
        if validation.warnings:
            lines.append(f"  warnings: {'; '.join(validation.warnings)}")
    if result.detail_url_examples:
        lines.append("")
        lines.append(colorize("Detail URL examples", Ansi.bold, Ansi.green))
        for url in result.detail_url_examples[:8]:
            lines.append(f"  {url}")
    lines.append("")
    return "\n".join(lines) + "\n"

def parse_args(argv: list[str]) -> argparse.Namespace:
    common_user_agent = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )
    if argv and argv[0] == "debug":
        parser = argparse.ArgumentParser(
            description="Debug Web Media rule resolution and print final item URL list.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        parser.add_argument("command")
        parser.add_argument("-r", "--rule-file", required=True, help="Path to a .wm rule file")
        parser.add_argument("--json", action="store_true", help="Print structured JSON")
        parser.add_argument("--limit", type=int, default=20, help="Maximum source candidates to inspect")
        parser.add_argument("--timeout", type=float, default=30.0)
        parser.add_argument("--desktop", action="store_true", help="Use desktop viewport")
        parser.add_argument("--headful", action="store_true", help="Run browser visibly")
        parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
        parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in debug output")
        parser.add_argument("--user-agent", default=common_user_agent)
        args = parser.parse_args(argv)
        args.mode = "debug"
        return args

    parser = argparse.ArgumentParser(
        description="Generate a Web Media Projection Resolver .wm rule from a listing page URL.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("url", help="Listing page URL, e.g. https://example.com/videos")
    parser.add_argument("--output", "-o", help="Write rule output to a file instead of stdout")
    parser.add_argument("--json", action="store_true", help="Print structured JSON instead of .wm rule text")
    parser.add_argument("--save-evidence", help="Write raw evidence/validation JSON to this file")
    parser.add_argument("--no-ai", action="store_true", help="Skip chat API and use local heuristics + validation only")
    parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY"))
    parser.add_argument("--base-url", default=os.getenv("OPENAI_BASE_URL") or os.getenv("AI_BASE_URL") or "https://api.openai.com/v1")
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL") or os.getenv("AI_MODEL") or "gpt-4o-mini")
    parser.add_argument("--no-response-format", action="store_true", help="Do not send OpenAI response_format=json_object")
    parser.add_argument("--timeout", type=float, default=30.0, help="Timeout for page loads and API calls")
    parser.add_argument("--sample-items", type=int, default=8, help="Samples per candidate group")
    parser.add_argument("--max-candidate-groups", type=int, default=6, help="Top visual/repeated card groups to analyze")
    parser.add_argument("--validate-hypotheses", type=int, default=5, help="Hypotheses to dry-run")
    parser.add_argument("--validation-limit", type=int, default=24, help="Candidate nodes to inspect per selector")
    parser.add_argument("--detail-probes", type=int, default=3, help="Detail/intermediate pages to open per hypothesis")
    parser.add_argument("--scroll-steps", type=int, default=3, help="Listing page scroll passes for lazy content")
    parser.add_argument("--no-click-play", action="store_true", help="Deprecated: click-play probing is disabled by a hardcoded v3 switch")
    parser.add_argument("--max-items", type=int, default=50, help="Generated resolver max_items value")
    parser.add_argument("--desktop", action="store_true", help="Use desktop viewport instead of mobile")
    parser.add_argument("--headful", action="store_true", help="Run browser visibly for debugging")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in terminal output")
    parser.add_argument("--user-agent", default=common_user_agent)
    args = parser.parse_args(argv)
    args.mode = "generate"
    return args


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    configure_logging(args.log_level)
    enable_color((sys.stderr.isatty() or sys.stdout.isatty()) and not getattr(args, "no_color", False) and shutil.which("tput") is not None)

    try:
        if args.mode == "debug":
            items, events, diagnoses, rule = debug_rule(args)
            if args.json:
                print(json.dumps({
                    "rule": rule,
                    "events": [to_plain(event) for event in events],
                    "diagnoses": diagnoses,
                    "items": items,
                }, ensure_ascii=False, indent=2))
            else:
                print(render_debug_report(rule, items, events, diagnoses), end="")
            return 0

        result = run_generation(args)
        if not args.json:
            print(render_generation_report(result), file=sys.stderr, end="")
        if args.save_evidence:
            with open(args.save_evidence, "w", encoding="utf-8") as file:
                json.dump(json_output(result), file, ensure_ascii=False, indent=2)
                file.write("\n")

        if args.json:
            output = json.dumps(json_output(result), ensure_ascii=False, indent=2) + "\n"
        else:
            output = render_rule(
                result.rule,
                confidence=result.confidence,
                reasoning=result.reasoning,
                detail_url_examples=result.detail_url_examples,
            )

        if args.output:
            with open(args.output, "w", encoding="utf-8") as file:
                file.write(output)
        else:
            print(output, end="")
        return 0
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("script failed")
        print(f"failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
