import pytest

from zwmp_rule import build_projection_tree, extract_media_urls, format_rule, is_media_url, parse_rule
from zwmp_rule.parser import RuleError
from zwmp_rule.types import ProjectionItem, ProjectionMedia


def test_parse_and_format_minimal_rule():
    rule = parse_rule(
        """
        # comment
        source=https://example.com/videos
        candidate_selector=a:has(img)
        projection=by-item
        media_type=video
        """
    )

    assert str(rule.source) == "https://example.com/videos"
    assert rule.candidate_selector == "a:has(img)"
    assert "candidate_selector=a:has(img)" in format_rule(rule)


def test_parse_invalid_int_reports_line():
    with pytest.raises(RuleError) as error:
        parse_rule("source=https://example.com\ncandidate_selector=a\nmax_items=nope")

    assert error.value.line == 3


def test_parse_supported_detail_fields():
    rule = parse_rule(
        """
        source=https://example.com
        candidate_selector=.video-card
        detail_url_selector=a.btn-play
        detail_url_mode=expand
        detail_url_selector_2=a.source
        detail_url_stop_when_media_found=false
        max_detail_concurrency=4
        media_selector=video source
        play_button_selector=button.play
        selector_wait_timeout=1.5
        network_sniff_timeout=5.0
        network_sniff_idle_timeout=1.0
        media_delivery=redirect
        """
    )

    rendered = format_rule(rule)
    assert "detail_url_selector=a.btn-play" in rendered
    assert "detail_url_mode=expand" in rendered
    assert "selector_wait_timeout=1.5" in rendered
    assert "network_sniff_timeout=5.0" in rendered
    assert "media_delivery=redirect" in rendered


def test_media_type_matching_does_not_treat_image_as_video():
    assert is_media_url("https://cdn.example.com/movie.m3u8?token=1", "video")
    assert not is_media_url("https://cdn.example.com/cover.jpg", "video")
    assert is_media_url("https://cdn.example.com/cover.jpg", "image")


def test_extract_media_urls_resolves_relative_sources():
    urls = extract_media_urls(
        """
        <video><source src="/media/one.mp4?x=1"></video>
        <img src="/cover.jpg">
        <script>const u = "https://cdn.example.com/two.m3u8";</script>
        """,
        "https://example.com/page",
        "video",
    )

    assert "https://example.com/media/one.mp4?x=1" in urls
    assert "https://cdn.example.com/two.m3u8" in urls
    assert all("cover" not in url for url in urls)


def test_build_projection_tree_by_item():
    items = [ProjectionItem(id="i1", title="Episode 1", detail_url="https://example.com/e1", media_ids=["m1"])]
    media = [ProjectionMedia(id="m1", item_id="i1", url="https://cdn.example.com/e1.mp4", type="video", extension="mp4")]

    tree = build_projection_tree("by-item", items, media)

    assert tree[0].name == "Episode 1"
    assert tree[0].kind == "directory"
    assert tree[0].children[-1].name == "Episode 1.mp4"
