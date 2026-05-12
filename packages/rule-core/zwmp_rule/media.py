from __future__ import annotations

import html
import re
from urllib.parse import urljoin, urlparse

from .types import MediaType

VIDEO_EXTENSIONS = {"mp4", "webm", "m3u8", "mpd", "mov", "m4v", "m4s", "ts"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "flac", "ogg", "opus", "wav", "aac"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif", "svg", "bmp", "heic", "heif"}
ALL_EXTENSIONS = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS | IMAGE_EXTENSIONS


def normalize_media_url(raw_url: str, base_url: str | None = None) -> str:
    value = html.unescape(raw_url.strip().strip("\"'")).replace("\\/", "/")
    value = re.split(r"[\"'<>\s]", value, maxsplit=1)[0] if value else ""
    if base_url:
        return urljoin(base_url, value)
    return value


def extension_for_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "." not in path:
        return None
    return path.rsplit(".", 1)[-1]


def is_media_url(url: str, media_type: str | MediaType = MediaType.VIDEO) -> bool:
    ext = extension_for_url(normalize_media_url(url))
    if not ext:
        return False
    wanted = MediaType(media_type)
    if wanted == MediaType.ALL:
        return ext in ALL_EXTENSIONS
    if wanted == MediaType.VIDEO:
        return ext in VIDEO_EXTENSIONS
    if wanted == MediaType.AUDIO:
        return ext in AUDIO_EXTENSIONS
    if wanted == MediaType.IMAGE:
        return ext in IMAGE_EXTENSIONS
    return False


MEDIA_LITERAL_RE = re.compile(
    r"https?:\\?/\\?/[^\s\"'<>]+?\.(?:m3u8|mpd|mp4|webm|mov|m4v|m4s|ts|mp3|m4a|aac|flac|ogg|opus|wav|jpe?g|png|gif|webp|avif|svg|bmp|heic|heif)(?:\?[^\s\"'<>]*)?",
    re.I,
)


def extract_media_urls(html_text: str, base_url: str, media_type: str | MediaType = MediaType.VIDEO) -> list[str]:
    raws: list[str] = []
    tag_names = "video|audio|source|img"
    raws.extend(
        re.findall(
            rf"<(?:{tag_names})\b[^>]*(?:src|data-src|data-original|data-lazy-src)=[\"']([^\"']+)[\"']",
            html_text,
            re.I,
        )
    )
    for srcset in re.findall(r"\bsrcset=[\"']([^\"']+)[\"']", html_text, re.I):
        raws.extend(part.strip().split()[0] for part in srcset.split(",") if part.strip())
    raws.extend(
        value
        for value in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"']", html_text, re.I)
        if is_media_url(value, media_type)
    )
    raws.extend(MEDIA_LITERAL_RE.findall(html_text))

    seen: set[str] = set()
    urls: list[str] = []
    for raw in raws:
        normalized = normalize_media_url(raw, base_url)
        if normalized and is_media_url(normalized, media_type) and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)
    return urls

