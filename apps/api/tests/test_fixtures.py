from pathlib import Path

from zwmp_api.heuristics import analyze_site, build_projection_from_rule
from zwmp_rule import parse_rule


def test_static_fixture_generates_candidates():
    html = Path(__file__).with_name("fixtures").joinpath("static_grid.html").read_text()
    profile, drafts, events = analyze_site(html, "https://example.com/videos", "video")

    assert profile.category in {"streaming", "media"}
    assert drafts
    assert events


def test_projection_extracts_video():
    html = Path(__file__).with_name("fixtures").joinpath("direct_video.html").read_text()
    rule = parse_rule(
        """
        source=https://example.com/videos
        candidate_selector=a:has(img)
        media_type=video
        projection=by-item
        """
    )
    projection = build_projection_from_rule(rule, html, "https://example.com/videos")

    assert projection.items
    assert projection.media
    assert projection.media[0].url == "https://example.com/media/one.mp4"

