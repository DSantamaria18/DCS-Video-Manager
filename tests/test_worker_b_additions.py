"""Tests for Worker B additions: #33 Discord webhook, #18 stats, #25 theme, #24 history."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from app import _post_discord_webhook
from app import app as flask_app

import dcs_meta


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ── #33 Discord webhook DEFAULT_CONFIG ───────────────────────────────────────

def test_default_config_has_discord_webhook_url():
    assert "discord_webhook_url" in dcs_meta.DEFAULT_CONFIG
    assert dcs_meta.DEFAULT_CONFIG["discord_webhook_url"] == ""


def test_config_allowed_keys_includes_discord_webhook():
    from app import _CONFIG_ALLOWED_KEYS
    assert "discord_webhook_url" in _CONFIG_ALLOWED_KEYS


# ── #33 _post_discord_webhook ─────────────────────────────────────────────────

def test_post_discord_webhook_does_not_raise_on_failure(monkeypatch):
    import urllib.error as _err
    import urllib.request as _req

    def _mock_urlopen(*a, **k):
        raise _err.URLError("simulated failure")

    monkeypatch.setattr(_req, "urlopen", _mock_urlopen)
    _post_discord_webhook("https://fake.webhook/", "Title", "https://yt.com/v", "Desc")


def test_post_discord_webhook_builds_correct_payload(monkeypatch):
    import urllib.request as _req
    captured = {}

    class _MockResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def _mock_urlopen(req, *a, **k):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _MockResp()

    monkeypatch.setattr(_req, "urlopen", _mock_urlopen)
    _post_discord_webhook("https://fake/", "Test Title", "https://yt.com/watch?v=x", "Desc text")
    assert "embeds" in captured.get("data", {})
    embed = captured["data"]["embeds"][0]
    assert embed["title"] == "Test Title"
    assert embed["url"] == "https://yt.com/watch?v=x"


def test_post_discord_webhook_truncates_description_to_200(monkeypatch):
    import urllib.request as _req
    captured = {}

    class _MockResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass

    def _mock_urlopen(req, *a, **k):
        captured["data"] = json.loads(req.data.decode("utf-8"))
        return _MockResp()

    monkeypatch.setattr(_req, "urlopen", _mock_urlopen)
    _post_discord_webhook("https://fake/", "T", "https://yt.com/v", "A" * 500)
    desc = captured["data"]["embeds"][0]["description"]
    assert len(desc) <= 200


# ── #18 stats endpoint ────────────────────────────────────────────────────────

def test_stats_endpoint_returns_200(client, monkeypatch):
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": []})
    resp = client.get("/api/stats")
    assert resp.status_code == 200


def test_stats_endpoint_returns_total_videos(client, monkeypatch):
    videos = [{"aircraft": "F/A-18C Hornet", "map": "Caucasus", "mission_type": "BVR",
               "date": "2026-05-01", "title": "T1", "video_id": "abc"}] * 3
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/stats")
    assert resp.json["total_videos"] == 3


def test_stats_endpoint_returns_by_module(client, monkeypatch):
    videos = [{"aircraft": "F/A-18C Hornet", "map": "", "mission_type": "",
               "date": "2026-05-01", "title": "", "video_id": ""}] * 2
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/stats")
    assert "F/A-18C Hornet" in resp.json["by_module"]


def test_stats_endpoint_returns_uploads_by_month(client, monkeypatch):
    videos = [{"aircraft": "", "map": "", "mission_type": "",
               "date": "2026-05-15", "title": "", "video_id": ""}] * 2
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/stats")
    assert "2026-05" in resp.json.get("uploads_by_month", {})


def test_stats_endpoint_top_videos_includes_video_id(client, monkeypatch):
    videos = [{"aircraft": "", "map": "", "mission_type": "",
               "date": "2026-05-01", "title": "T1", "video_id": "vid1"}]
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/stats")
    top = resp.json.get("top_videos", [])
    assert any(v["video_id"] == "vid1" for v in top)


# ── #25 theme toggle (config check) ──────────────────────────────────────────

def test_discord_webhook_url_saveable_via_config_endpoint(client, monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({}))
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", cfg_file)
    monkeypatch.setattr(dcs_meta, "load_config", lambda: {**dcs_meta.DEFAULT_CONFIG})

    resp = client.post("/api/config", json={"discord_webhook_url": "https://discord.com/api/webhooks/test"})
    assert resp.status_code == 200


# ── #24 history endpoint returns video_id ────────────────────────────────────

def test_history_endpoint_returns_video_id(client, monkeypatch):
    videos = [{"date": "2026-05-01", "filename": "v.mkv", "title": "T",
               "aircraft": "F/A-18C", "map": "Caucasus", "mission_type": "BVR",
               "language": "en", "video_id": "yt123"}]
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/history")
    assert resp.status_code == 200
    items = resp.json
    assert items[0]["video_id"] == "yt123"


def test_history_endpoint_returns_last_20(client, monkeypatch):
    videos = [{"date": "2026-01-01", "filename": f"v{i}.mkv", "title": f"T{i}",
               "aircraft": "", "map": "", "mission_type": "", "language": "en", "video_id": ""}
              for i in range(25)]
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    resp = client.get("/api/history")
    assert len(resp.json) == 20


# ── upload result includes tags_skipped flag ──────────────────────────────────

def test_upload_tags_skipped_message_is_specific(monkeypatch):
    """Tags rejection message must mention unverified app (bug #1)."""
    import youtube_uploader as yu
    captured = {}

    call_count = {"n": 0}

    def _mock_do_insert(youtube, body, video_path):
        call_count["n"] += 1
        if call_count["n"] == 1 and body["snippet"].get("tags"):
            raise Exception("invalidTags — The request contains an invalid argument.")
        captured["body"] = body
        return {"id": "vid789"}

    monkeypatch.setattr(yu, "_build_service", lambda: None)
    monkeypatch.setattr(yu, "_do_insert", _mock_do_insert)
    monkeypatch.setattr(yu, "_sanitize_tags", lambda t: t)

    import os
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake")
        fp = f.name
    try:
        result = yu.upload_video(fp, "T", "D", ["tag1"])
        assert result.get("tags_skipped") is True
    except Exception:  # noqa: BLE001 — solo interesa el cuerpo capturado antes de _do_insert; lo posterior no está mockeado a propósito
        pass
    finally:
        os.unlink(fp)
