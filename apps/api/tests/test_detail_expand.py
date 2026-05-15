from pathlib import Path

import pytest

from zwmp_api.config import Settings
from zwmp_api.fetcher import LoadedPage
from zwmp_api.jobs import JobManager
from zwmp_api.storage import Storage


class FakeFetcher:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages

    async def load(self, url: str, force_desktop: bool = True, fast_mode: bool = False) -> LoadedPage:
        return LoadedPage(requested_url=url, final_url=url, html=self.pages[url], network_media=[], browser_used=True)


@pytest.mark.asyncio
async def test_detail_url_expand_creates_resource_items(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path,
        cache_db=tmp_path / "cache.sqlite3",
        rule_output_dir=tmp_path / "rules",
    )
    manager = JobManager(settings, Storage(settings))
    manager.fetcher = FakeFetcher(
        {
            "https://example.com/list": '<a href="https://example.com/season"><img src="/cover.jpg">Show</a>',
            "https://example.com/season": """
              <a class="episode" href="https://example.com/play/1">Episode 1</a>
              <a class="episode" href="https://example.com/play/2">Episode 2</a>
            """,
            "https://example.com/play/1": '<video><source src="https://cdn.example.com/1.mp4"></video>',
            "https://example.com/play/2": '<video><source src="https://cdn.example.com/2.mp4"></video>',
        }
    )
    rule_text = """
    source=https://example.com/list
    candidate_selector=a:has(img)
    detail_url_selector=a.episode
    detail_url_mode=expand
    media_type=video
    projection=by-item
    """

    projection, _ = await manager._projection_for_rule(rule_text)

    assert len(projection.items) == 2
    assert len(projection.media) == 2
    assert projection.tree[0].name.startswith("Show - 1")
