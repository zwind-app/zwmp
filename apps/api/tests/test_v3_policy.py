from zwmp_api import v3_engine as v3
from zwmp_api.v3_adapter import projection_from_debug


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
