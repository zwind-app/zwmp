from zwmp_api import v3_engine as v3
from zwmp_api.config import Settings
from zwmp_api.v3_adapter import preview_detail_probes, projection_from_debug


def test_v3_detail_hop_policy_expands_episode_links():
    probe = v3.DetailProbe(item_title="Show", item_url="https://example.com/show")
    probe.dom_media = [{"url": "https://cdn.example.com/show.m3u8", "kind": "video"}]
    probe.episode_links = [
        v3.LinkEvidence(href="/play/1", abs_url="https://example.com/play/1", selector="a.episode"),
        v3.LinkEvidence(href="/play/2", abs_url="https://example.com/play/2", selector="a.episode"),
    ]

    repair = v3.detail_hop_repair_from_probes([probe], "video")

    assert repair["detail_url_selector"] == "a.episode"
    assert repair["detail_url_mode"] == "expand"


def test_v3_sanitize_removes_disabled_player_fields():
    rule = v3.sanitize_rule(
        {
            "source": "https://example.com/videos",
            "candidate_selector": ".card",
            "media_selector": "video source",
            "play_button_selector": "button.play",
            "media_delivery": "direct",
        },
        "https://example.com/videos",
        50,
    )

    assert "media_selector" not in rule
    assert "play_button_selector" not in rule
    assert rule["media_delivery"] == "redirect"
    assert rule["fast_mode"] is True


def test_v3_sanitize_defaults_media_delivery_to_redirect():
    rule = v3.sanitize_rule(
        {
            "source": "https://example.com/videos",
            "candidate_selector": ".card",
        },
        "https://example.com/videos",
        50,
    )

    assert rule["media_delivery"] == "redirect"


def test_preview_projection_uses_detail_probe_media():
    probe = v3.DetailProbe(item_title="Episode One", item_url="https://example.com/watch/1")
    probe.final_url = "https://example.com/watch/1"
    probe.dom_media = [{"url": "https://cdn.example.com/one.mp4", "kind": "video", "source": "dom"}]

    projection = projection_from_debug(
        [{"title": "Episode One", "url": "https://example.com/watch/1"}],
        [],
        [],
        {"media_type": "video", "projection": "by-item"},
        [probe],
    )

    assert len(projection.items) == 1
    assert len(projection.media) == 1
    assert projection.items[0].status == "resolved"
    assert projection.media[0].url == "https://cdn.example.com/one.mp4"


def test_preview_detail_probes_all_items_not_probe_limit(monkeypatch):
    probed_urls = []

    class FakeRuntime:
        def __init__(self, proxy_url, headless=True):
            self.proxy_url = proxy_url
            self.headless = headless

        def close(self):
            return None

    def fake_probe(runtime, item, rule, **kwargs):
        probed_urls.append(item["href"])
        return v3.DetailProbe(item_title=item["title"], item_url=item["href"])

    monkeypatch.setattr(v3, "BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(v3, "probe_detail_page", fake_probe)
    items = [{"title": f"Item {index}", "url": f"https://example.com/watch/{index}"} for index in range(5)]

    probes = preview_detail_probes(items, {"media_type": "video"}, Settings(probe_items=3))

    assert len(probes) == 5
    assert probed_urls == [item["url"] for item in items]


def test_preview_detail_probes_reports_incremental_results(monkeypatch):
    class FakeRuntime:
        def __init__(self, proxy_url, headless=True):
            self.proxy_url = proxy_url
            self.headless = headless

        def close(self):
            return None

    def fake_probe(runtime, item, rule, **kwargs):
        probe = v3.DetailProbe(item_title=item["title"], item_url=item["href"])
        probe.final_url = item["href"]
        probe.dom_media = [{"url": f"{item['href']}.mp4", "kind": "video", "source": "dom"}]
        return probe

    increments = []
    monkeypatch.setattr(v3, "BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(v3, "probe_detail_page", fake_probe)
    items = [{"title": f"Item {index}", "url": f"https://example.com/watch/{index}"} for index in range(3)]

    preview_detail_probes(
        items,
        {"media_type": "video"},
        Settings(probe_items=1),
        on_probe=lambda index, total, probes: increments.append((index, total, len(probes))),
    )

    assert increments == [(1, 3, 1), (2, 3, 2), (3, 3, 3)]
