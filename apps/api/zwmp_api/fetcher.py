from __future__ import annotations

import asyncio
import urllib.request
from dataclasses import dataclass

from zwmp_rule.security import assert_public_http_url

from .config import Settings


@dataclass
class LoadedPage:
    requested_url: str
    final_url: str
    html: str
    network_media: list[str]


class PageFetcher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def load(self, url: str, force_desktop: bool = True) -> LoadedPage:
        assert_public_http_url(url)
        playwright_page = await self._load_with_playwright(url, force_desktop)
        if playwright_page:
            return playwright_page
        return await asyncio.to_thread(self._load_with_urllib, url, force_desktop)

    async def _load_with_playwright(self, url: str, force_desktop: bool) -> LoadedPage | None:
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception:
            return None

        media_urls: list[str] = []
        browser = None
        playwright = await async_playwright().start()
        try:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context(
                ignore_https_errors=True,
                user_agent=desktop_user_agent() if force_desktop else None,
            )
            page = await context.new_page()

            def on_request(request) -> None:  # type: ignore[no-untyped-def]
                if request.resource_type in {"media", "xhr", "fetch"}:
                    media_urls.append(request.url)

            page.on("request", on_request)
            await page.goto(url, wait_until="domcontentloaded", timeout=int(self.settings.request_timeout_seconds * 1000))
            await page.wait_for_timeout(900)
            html = await page.content()
            if len(html.encode("utf-8", errors="ignore")) > self.settings.max_html_bytes:
                raise RuntimeError("page HTML exceeded maximum size")
            final_url = page.url
            await context.close()
            return LoadedPage(requested_url=url, final_url=final_url, html=html, network_media=media_urls)
        except Exception:
            return None
        finally:
            if browser:
                await browser.close()
            await playwright.stop()

    def _load_with_urllib(self, url: str, force_desktop: bool) -> LoadedPage:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": desktop_user_agent() if force_desktop else mobile_user_agent(),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
        )
        with urllib.request.urlopen(request, timeout=self.settings.request_timeout_seconds) as response:
            raw = response.read(self.settings.max_html_bytes + 1)
            if len(raw) > self.settings.max_html_bytes:
                raise RuntimeError("page HTML exceeded maximum size")
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
            return LoadedPage(requested_url=url, final_url=response.geturl(), html=html, network_media=[])


def desktop_user_agent() -> str:
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )


def mobile_user_agent() -> str:
    return (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    )

