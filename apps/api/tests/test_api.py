from fastapi.testclient import TestClient

from zwmp_api.main import app
from zwmp_api.storage import Storage, normalized_url_pattern
from zwmp_rule.types import ProjectionResult


def test_health():
    client = TestClient(app)
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_rules_and_proxy_are_not_public():
    client = TestClient(app)

    assert client.get("/api/rules").status_code == 404
    assert client.get("/api/proxy/session/media").status_code == 404


def test_normalized_url_pattern_keeps_query_keys_without_values():
    assert (
        normalized_url_pattern("https://Example.com/path/video?id=123&page=9&utm=x#frag")
        == "https://example.com/path/video?id=&page=&utm="
    )


def test_ai_and_local_cache_are_separate(tmp_path):
    from zwmp_api.config import Settings

    storage = Storage(
        Settings(
            data_dir=tmp_path / "data",
            cache_db=tmp_path / "cache.sqlite3",
            rule_output_dir=tmp_path / "rules",
        )
    )
    key = storage.cache_key("https://example.com/videos?id=1", "video", {})

    storage.set_cache(key, "local-rule", "local")
    storage.set_cache(key, "ai-rule", "ai")

    assert storage.get_cached_rule_id(key, "ai") == "ai-rule"
    assert storage.get_cached_rule_id(key, "local") == "local-rule"


def test_share_roundtrip():
    client = TestClient(app)
    payload = {
        "rule_text": "source=https://example.com/videos\ncandidate_selector=a\nmedia_type=video\n",
        "projection": ProjectionResult().model_dump(),
        "runtime_notices": [],
        "warnings": [],
    }

    created = client.post("/api/shares", json=payload)
    assert created.status_code == 200
    share_id = created.json()["id"]

    fetched = client.get(f"/api/shares/{share_id}")
    assert fetched.status_code == 200
    assert fetched.json()["rule_text"] == payload["rule_text"]
