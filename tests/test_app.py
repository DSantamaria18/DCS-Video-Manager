import json
from unittest.mock import patch

import app as app_module
import pytest
from app import app as flask_app

import dcs_meta


@pytest.fixture
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


# ── GET /api/config ───────────────────────────────────────────────────────────

def test_get_config_returns_200(client):
    with patch("dcs_meta.load_config", return_value={"model": "gemini-2.5-flash"}):
        resp = client.get("/api/config")
    assert resp.status_code == 200
    assert resp.json["model"] == "gemini-2.5-flash"


# ── GET /api/history ──────────────────────────────────────────────────────────

def test_get_history_empty(client):
    with patch("dcs_meta.load_memory", return_value={"videos": []}):
        resp = client.get("/api/history")
    assert resp.status_code == 200
    assert resp.json == []


def test_get_history_returns_last_20(client):
    videos = [{"title": f"v{i}"} for i in range(25)]
    with patch("dcs_meta.load_memory", return_value={"videos": videos}):
        resp = client.get("/api/history")
    assert resp.status_code == 200
    assert len(resp.json) == 20
    assert resp.json[-1]["title"] == "v24"


# ── POST /api/analyze ─────────────────────────────────────────────────────────

def test_analyze_missing_path_returns_400(client):
    resp = client.post("/api/analyze", json={})
    assert resp.status_code == 400


def test_analyze_file_not_found_returns_404(client):
    resp = client.post("/api/analyze", json={"video_path": "/nonexistent/video.mp4"})
    assert resp.status_code == 404


def test_analyze_no_api_key_returns_500(client, tmp_path, monkeypatch):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    resp = client.post("/api/analyze", json={"video_path": str(video)})
    assert resp.status_code == 500
    assert "GEMINI_API_KEY" in resp.json["error"]


def test_analyze_returns_job_id(client, tmp_path, monkeypatch):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    # Sin congelar el hilo, el job sigue vivo durante el test siguiente y ejecuta sus mocks (flaky en CI).
    with patch("app.threading.Thread"):
        resp = client.post("/api/analyze", json={"video_path": str(video)})
    assert resp.status_code == 200
    assert "job_id" in resp.json
    assert len(resp.json["job_id"]) == 8


def test_analyze_cache_hit_skips_gemini_call(client, tmp_path, monkeypatch):
    """FEA-02: a cache hit must skip frame extraction and the Gemini call entirely."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    def run_now(target=None, daemon=None):
        target()
        return type("_SyncThread", (), {"start": lambda self: None})()

    with patch("dcs_meta.get_cached_metadata", return_value={"title": "Cached"}), \
         patch("dcs_meta.generate_metadata") as mock_generate, \
         patch("dcs_meta.extract_frames") as mock_extract, \
         patch("dcs_meta.set_cached_metadata") as mock_set_cache, \
         patch("dcs_meta.save_output", return_value=(tmp_path / "t.txt", tmp_path / "t.json")), \
         patch("dcs_meta.update_memory"), \
         patch("app.threading.Thread", side_effect=run_now):
        resp = client.post("/api/analyze", json={"video_path": str(video)})

    job_id = resp.json["job_id"]
    status = client.get(f"/api/status/{job_id}")
    assert status.json["status"] == "done"
    assert status.json["result"]["metadata"]["title"] == "Cached"
    mock_generate.assert_not_called()
    mock_extract.assert_not_called()
    mock_set_cache.assert_not_called()


def _run_analyze_sync(client, video, payload, **patches):
    def run_now(target=None, daemon=None):
        target()
        return type("_SyncThread", (), {"start": lambda self: None})()

    with patch("dcs_meta.extract_frames", return_value=["f.jpg"]) as mock_extract, \
         patch("dcs_meta.generate_metadata", return_value={"title": "Fresh"}) as mock_generate, \
         patch("dcs_meta.set_cached_metadata") as mock_set_cache, \
         patch("dcs_meta.save_output", return_value=(video.parent / "t.txt", video.parent / "t.json")), \
         patch("dcs_meta.update_memory"), \
         patch("app.threading.Thread", side_effect=run_now), \
         patch("dcs_meta.get_cached_metadata", **patches) as mock_get_cache:
        resp = client.post("/api/analyze", json={"video_path": str(video), **payload})
    return resp, mock_get_cache, mock_generate, mock_extract, mock_set_cache


def test_analyze_force_ignores_cache_and_overwrites_it(client, tmp_path, monkeypatch):
    """BUG-05: 're-analizar' debe saltarse la caché y reescribirla con el resultado nuevo."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    resp, mock_get, mock_generate, _, mock_set = _run_analyze_sync(
        client, video, {"force": True}, return_value={"title": "Cached"})

    assert client.get(f"/api/status/{resp.json['job_id']}").json["result"]["metadata"]["title"] == "Fresh"
    mock_get.assert_not_called()
    mock_generate.assert_called_once()
    mock_set.assert_called_once()


def test_analyze_passes_settings_fingerprint_to_cache(client, tmp_path, monkeypatch):
    """BUG-05: cambiar el contexto cambia la huella con la que se consulta y se guarda la caché."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    _, get_a, _, _, set_a = _run_analyze_sync(client, video, {"context": "uno"}, return_value=None)
    _, get_b, _, _, _ = _run_analyze_sync(client, video, {"context": "dos"}, return_value=None)

    fp_a = get_a.call_args.kwargs["fingerprint"]
    assert fp_a and fp_a != get_b.call_args.kwargs["fingerprint"]
    assert set_a.call_args.kwargs["fingerprint"] == fp_a


# ── GET /api/status/<job_id> ──────────────────────────────────────────────────

def test_status_unknown_job_returns_404(client):
    resp = client.get("/api/status/doesnotexist")
    assert resp.status_code == 404


def test_status_known_job_returns_state(client, tmp_path, monkeypatch):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    # Freeze the background thread so the job stays in "running" state
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/analyze", json={"video_path": str(video)})

    job_id = resp.json["job_id"]
    status = client.get(f"/api/status/{job_id}")
    assert status.status_code == 200
    assert status.json["status"] == "running"
    assert status.json["progress"] == 0


# ── POST /api/upload_youtube ──────────────────────────────────────────────────

def test_upload_youtube_missing_fields_returns_400(client):
    resp = client.post("/api/upload_youtube", json={})
    assert resp.status_code == 400


def test_upload_youtube_missing_metadata_returns_400(client):
    resp = client.post("/api/upload_youtube", json={"video_path": "/some/video.mp4"})
    assert resp.status_code == 400


def test_upload_youtube_not_authenticated_returns_job_id(client):
    """Upload is now async — endpoint always returns 200 with job_id; auth errors surface via status poll."""
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/upload_youtube", json={
            "video_path": "/some/video.mp4",
            "metadata": {"title": "Test", "description": "desc", "tags": []}
        })
    assert resp.status_code == 200
    assert "job_id" in resp.json


# ── POST /api/upload_youtube — thumbnail path resolution ─────────────────────

def test_upload_youtube_passes_thumbnail_path(client, tmp_path):
    """Endpoint must resolve /output/file.jpg to a local path and pass it to upload_video."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    thumb = output_dir / "test_thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X",
                     "status": "uploaded", "privacy": "private",
                     "tags_skipped": False, "playlists_added": [],
                     "thumbnail_set": True}

    with patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv, \
         patch.object(app_module, "OUTPUT_DIR", output_dir):
        resp = client.post("/api/upload_youtube", json={
            "video_path": "/fake/video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
            "thumbnail_url": "/output/test_thumb.jpg",
        })

    assert resp.status_code == 200
    mock_uv.assert_called_once()
    assert mock_uv.call_args.kwargs["thumbnail_path"] == str(thumb)


def test_upload_youtube_stores_video_id_in_memory(client, tmp_path):
    """After upload, the video_id returned by YouTube must be patched into history."""
    upload_result = {
        "video_id": "testVidId",
        "url": "https://youtu.be/testVidId",
        "status": "uploaded", "privacy": "private",
        "tags_skipped": False, "playlists_added": [],
    }
    with patch("youtube_uploader.upload_video", return_value=upload_result), \
         patch("dcs_meta.update_memory_video_id") as mock_patch_id:
        resp = client.post("/api/upload_youtube", json={
            "video_path": "/fake/my_video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
        })
    assert resp.status_code == 200
    mock_patch_id.assert_called_once_with("my_video.mp4", "testVidId")


def test_upload_youtube_skips_video_id_patch_when_missing(client):
    """If upload result has no video_id, update_memory_video_id must NOT be called."""
    upload_result = {
        "url": "https://youtu.be/X",
        "status": "uploaded", "privacy": "private",
        "tags_skipped": False, "playlists_added": [],
    }
    with patch("youtube_uploader.upload_video", return_value=upload_result), \
         patch("dcs_meta.update_memory_video_id") as mock_patch_id:
        resp = client.post("/api/upload_youtube", json={
            "video_path": "/fake/my_video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
        })
    assert resp.status_code == 200
    mock_patch_id.assert_not_called()


def test_upload_youtube_missing_thumbnail_file_ignored(client):
    """Endpoint must proceed with upload even if thumbnail file does not exist."""
    upload_result = {"video_id": "Y", "url": "https://youtu.be/Y",
                     "status": "uploaded", "privacy": "private",
                     "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        client.post("/api/upload_youtube", json={
            "video_path": "/fake/video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
            "thumbnail_url": "/output/nonexistent_thumb.jpg"
        })

    # upload_video should have been called with thumbnail_path=None
    mock_uv.assert_called_once()
    assert mock_uv.call_args.kwargs.get("thumbnail_path") is None


def test_upload_youtube_passes_publish_at_to_upload_video(client):
    """publish_at ISO string must be forwarded to upload_video."""
    upload_result = {"video_id": "Z", "url": "https://youtu.be/Z",
                     "status": "uploaded", "privacy": "private",
                     "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        client.post("/api/upload_youtube", json={
            "video_path": "/fake/video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
            "publish_at": "2026-06-01T19:00:00Z"
        })

    mock_uv.assert_called_once()
    assert mock_uv.call_args.kwargs.get("publish_at") == "2026-06-01T19:00:00Z"


def test_upload_youtube_omits_publish_at_when_empty(client):
    """Empty publish_at string must become None (not forwarded as empty string)."""
    upload_result = {"video_id": "Z2", "url": "https://youtu.be/Z2",
                     "status": "uploaded", "privacy": "private",
                     "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        client.post("/api/upload_youtube", json={
            "video_path": "/fake/video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
            "publish_at": ""
        })

    mock_uv.assert_called_once()
    assert mock_uv.call_args.kwargs.get("publish_at") is None


# ── GET /api/youtube/status ───────────────────────────────────────────────────

def test_youtube_status_returns_authenticated_key(client):
    resp = client.get("/api/youtube/status")
    assert resp.status_code == 200
    assert "authenticated" in resp.json


# ── POST /api/config ──────────────────────────────────────────────────────────

VALID_CONFIG_PAYLOAD = {
    "channel_name": "TestPilot",
    "channel_description": "Test channel",
    "squadron": "Test Squadron",
    "frames_to_extract": 6,
    "model": "gemini-2.5-flash",
    "default_links": {"twitter": "https://twitter.com/test"},
}


def test_post_config_saves_valid_config(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    with patch("dcs_meta.load_config", return_value=dict(VALID_CONFIG_PAYLOAD)):
        resp = client.post("/api/config", json=VALID_CONFIG_PAYLOAD)
    assert resp.status_code == 200
    assert resp.json["channel_name"] == "TestPilot"
    assert resp.json["frames_to_extract"] == 6


def test_post_config_invalid_frames_zero_returns_400(client):
    payload = {**VALID_CONFIG_PAYLOAD, "frames_to_extract": 0}
    resp = client.post("/api/config", json=payload)
    assert resp.status_code == 400
    assert "frames_to_extract" in resp.json["error"]


def test_post_config_invalid_frames_above_20_returns_400(client):
    payload = {**VALID_CONFIG_PAYLOAD, "frames_to_extract": 21}
    resp = client.post("/api/config", json=payload)
    assert resp.status_code == 400


def test_post_config_invalid_frames_string_returns_400(client):
    payload = {**VALID_CONFIG_PAYLOAD, "frames_to_extract": "many"}
    resp = client.post("/api/config", json=payload)
    assert resp.status_code == 400


def test_post_config_invalid_model_returns_400(client):
    payload = {**VALID_CONFIG_PAYLOAD, "model": "gpt-4o"}
    resp = client.post("/api/config", json=payload)
    assert resp.status_code == 400
    assert "model" in resp.json["error"].lower() or "Invalid" in resp.json["error"]


def test_post_config_no_body_returns_400(client):
    resp = client.post("/api/config", data="not json",
                       content_type="application/json")
    assert resp.status_code == 400


def test_post_config_merges_with_existing(client, tmp_path, monkeypatch):
    existing = {**VALID_CONFIG_PAYLOAD, "channel_name": "OldName", "squadron": "OldSquad"}
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    with patch("dcs_meta.load_config", return_value=existing):
        resp = client.post("/api/config", json={"channel_name": "NewName"})
    assert resp.status_code == 200
    assert resp.json["channel_name"] == "NewName"
    assert resp.json["squadron"] == "OldSquad"


def test_post_config_rejects_retired_gemini_models(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    for model in ("gemini-1.5-flash", "gemini-1.5-pro"):
        payload = {**VALID_CONFIG_PAYLOAD, "model": model}
        with patch("dcs_meta.load_config", return_value=dict(VALID_CONFIG_PAYLOAD)):
            resp = client.post("/api/config", json=payload)
        assert resp.status_code == 400, f"Expected 400 for retired model {model}"


def test_post_config_all_valid_gemini_models_accepted(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    for model in ("gemini-2.5-flash", "gemini-2.5-pro"):
        payload = {**VALID_CONFIG_PAYLOAD, "model": model}
        with patch("dcs_meta.load_config", return_value=dict(VALID_CONFIG_PAYLOAD)):
            resp = client.post("/api/config", json=payload)
        assert resp.status_code == 200, f"Expected 200 for model {model}"


# ── SEC-01: Discord secrets stored outside config.json ───────────────────────

def test_post_config_discord_secrets_written_to_secrets_file_not_config(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(dcs_meta, "SECRETS_PATH", tmp_path / "secrets.json")
    resp = client.post("/api/config", json={
        "discord_bot_token": "tok123",
        "discord_channel_id": "999",
    })
    assert resp.status_code == 200
    assert resp.json["discord_bot_token"] == "tok123"
    assert resp.json["discord_channel_id"] == "999"

    config_on_disk = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert "discord_bot_token" not in config_on_disk
    assert "discord_channel_id" not in config_on_disk

    secrets_on_disk = json.loads((tmp_path / "secrets.json").read_text(encoding="utf-8"))
    assert secrets_on_disk["discord_bot_token"] == "tok123"
    assert secrets_on_disk["discord_channel_id"] == "999"


def test_post_config_secrets_persist_across_unrelated_updates(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(dcs_meta, "SECRETS_PATH", tmp_path / "secrets.json")
    client.post("/api/config", json={"discord_bot_token": "tok123"})

    resp = client.post("/api/config", json={"channel_name": "NewName"})

    assert resp.status_code == 200
    assert resp.json["channel_name"] == "NewName"
    assert resp.json["discord_bot_token"] == "tok123"


def test_get_config_includes_discord_secrets_from_secrets_file(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    secrets_path = tmp_path / "secrets.json"
    monkeypatch.setattr(dcs_meta, "SECRETS_PATH", secrets_path)
    secrets_path.write_text(
        '{"discord_bot_token": "existing-tok", "discord_webhook_url": "", "discord_channel_id": ""}',
        encoding="utf-8",
    )

    resp = client.get("/api/config")

    assert resp.status_code == 200
    assert resp.json["discord_bot_token"] == "existing-tok"


# ── POST /api/suggest_playlists ──────────────────────────────────────────────

PLAYLISTS = [
    {"id": "PL1", "title": "F/A-18C Hornet Advanced"},
    {"id": "PL2", "title": "BVR Master Class"},
    {"id": "PL3", "title": "A-10C Warthog CAS"},
    {"id": "PL4", "title": "Campaign Highlights"},
    {"id": "PL5", "title": "DCS World Beginner"},
]


def test_suggest_playlists_matches_aircraft(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "F/A-18C Hornet", "mission_type": "", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL1" in resp.json["suggested"]


def test_suggest_playlists_matches_mission_type(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "", "mission_type": "BVR", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL2" in resp.json["suggested"]


def test_suggest_playlists_matches_campaign(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "", "mission_type": "", "campaign": "Campaign Highlights"},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL4" in resp.json["suggested"]


def test_suggest_playlists_no_match_still_includes_dcs_world(client):
    # UH-1H has no specific playlist but "DCS World Beginner" (PL5) is always included
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "UH-1H Huey", "mission_type": "Transport", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL5" in resp.json["suggested"]  # Rule 1: DCS World always included


def test_suggest_playlists_multiple_matches(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "A-10C Warthog", "mission_type": "CAS", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    suggested = resp.json["suggested"]
    assert "PL3" in suggested


def test_suggest_playlists_empty_metadata_still_returns_dcs_world(client):
    # Even empty metadata → Rule 1 always adds "DCS World" playlist
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "", "mission_type": "", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL5" in resp.json["suggested"]


def test_suggest_playlists_no_body_returns_400(client):
    resp = client.post("/api/suggest_playlists", data="bad",
                       content_type="application/json")
    assert resp.status_code == 400


def test_suggest_playlists_case_insensitive(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "f/a-18c hornet", "mission_type": "", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert "PL1" in resp.json["suggested"]


# ── _suggest_playlist_ids unit tests ─────────────────────────────────────────

def test_suggest_playlist_ids_pure_function():
    from app import _suggest_playlist_ids
    result = _suggest_playlist_ids(
        {"aircraft": "F/A-18C Hornet", "mission_type": "BVR", "campaign": ""},
        PLAYLISTS
    )
    assert "PL1" in result
    assert "PL2" in result
    assert "PL5" in result  # Rule 1: DCS World always included


def test_suggest_playlist_ids_empty_playlists():
    from app import _suggest_playlist_ids
    assert _suggest_playlist_ids({"aircraft": "Hornet"}, []) == []


def test_suggest_playlist_ids_dcs_world_always_included():
    from app import _suggest_playlist_ids
    playlists = [
        {"id": "DW", "title": "DCS World"},
        {"id": "XX", "title": "Unrelated Playlist"},
    ]
    result = _suggest_playlist_ids({"aircraft": "", "mission_type": "", "campaign": ""}, playlists)
    assert "DW" in result
    assert "XX" not in result


def test_suggest_playlist_ids_shorts_rule():
    from app import _suggest_playlist_ids
    playlists = [
        {"id": "SH", "title": "SHORTS"},
        {"id": "DW", "title": "DCS World"},
    ]
    result = _suggest_playlist_ids({"aircraft": "", "duration_s": 45}, playlists)
    assert "SH" in result  # Rule 3: < 60 s
    result_long = _suggest_playlist_ids({"aircraft": "", "duration_s": 300}, playlists)
    assert "SH" not in result_long


def test_suggest_playlist_ids_largos_rule():
    from app import _suggest_playlist_ids
    playlists = [
        {"id": "LG", "title": "LARGOS"},
        {"id": "DW", "title": "DCS World"},
    ]
    result = _suggest_playlist_ids({"aircraft": "", "duration_s": 2000}, playlists)
    assert "LG" in result  # Rule 4: > 1800 s
    result_short = _suggest_playlist_ids({"aircraft": "", "duration_s": 600}, playlists)
    assert "LG" not in result_short


# ── _compute_publish_at ────────────────────────────────────────────────────────

def test_compute_publish_at_order_1_returns_first_date():
    from app import _compute_publish_at
    result = _compute_publish_at("2026-06-01T19:00:00Z", 3, 1)
    assert result == "2026-06-01T19:00:00Z"


def test_compute_publish_at_order_3_adds_interval_times_two():
    from app import _compute_publish_at
    result = _compute_publish_at("2026-06-01T19:00:00Z", 3, 3)
    assert result == "2026-06-07T19:00:00Z"


# ── _validate_shorts_batch ──────────────────────────────────────────────────────

def test_validate_shorts_batch_empty_clips_returns_error():
    from app import _validate_shorts_batch
    error = _validate_shorts_batch({"clips": [], "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None
    assert "clips" in error.lower()


def test_validate_shorts_batch_more_than_15_clips_returns_error():
    from app import _validate_shorts_batch
    clips = [{"clip_path": "/x.mp4", "order": i} for i in range(16)]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None
    assert "15" in error


def test_validate_shorts_batch_nonexistent_clip_path_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clips = [{"clip_path": str(tmp_path / "missing.mp4"), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None


def test_validate_shorts_batch_missing_first_publish_at_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "interval_days": 1})
    assert error is not None
    assert "first_publish_at" in error


def test_validate_shorts_batch_invalid_interval_days_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 0})
    assert error is not None
    assert "interval_days" in error


def test_validate_shorts_batch_valid_payload_returns_none(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 3})
    assert error is None


# ── GET /api/description_templates ───────────────────────────────────────────

def test_get_description_templates_returns_all_six_keys(client):
    with patch("dcs_meta.load_config", return_value={"description_templates": {}}):
        resp = client.get("/api/description_templates")
    assert resp.status_code == 200
    data = resp.json
    assert set(data["templates"].keys()) == {
        "en_short", "en_medium", "en_long",
        "es_short", "es_medium", "es_long",
    }


def test_get_description_templates_reflects_custom_override(client):
    cfg = {"description_templates": {"en_medium": "MY CUSTOM"}}
    with patch("dcs_meta.load_config", return_value=cfg):
        resp = client.get("/api/description_templates")
    assert resp.json["templates"]["en_medium"] == "MY CUSTOM"
    assert "en_medium" in resp.json["customised"]


def test_get_description_templates_empty_custom_not_in_customised(client):
    cfg = {"description_templates": {"en_medium": ""}}
    with patch("dcs_meta.load_config", return_value=cfg):
        resp = client.get("/api/description_templates")
    assert "en_medium" not in resp.json["customised"]


# ── POST /api/config — description_templates merge ────────────────────────────

def test_post_config_saves_single_template_without_overwriting_others(client, tmp_path, monkeypatch):
    existing = {**VALID_CONFIG_PAYLOAD,
                "description_templates": {"en_long": "EXISTING LONG"}}
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    with patch("dcs_meta.load_config", return_value=existing):
        resp = client.post("/api/config", json={
            "description_templates": {"en_medium": "NEW MEDIUM"}
        })
    assert resp.status_code == 200
    dt = resp.json["description_templates"]
    assert dt["en_medium"] == "NEW MEDIUM"
    assert dt["en_long"] == "EXISTING LONG"


def test_post_config_rejects_invalid_template_key(client):
    resp = client.post("/api/config", json={
        "description_templates": {"xx_invalid": "content"}
    })
    assert resp.status_code == 400
    assert "Invalid template key" in resp.json["error"]


def test_post_config_rejects_non_dict_description_templates(client):
    resp = client.post("/api/config", json={"description_templates": "not a dict"})
    assert resp.status_code == 400


def test_post_config_accepts_empty_string_to_reset_template(client, tmp_path, monkeypatch):
    existing = {**VALID_CONFIG_PAYLOAD,
                "description_templates": {"en_short": "CUSTOM"}}
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    with patch("dcs_meta.load_config", return_value=existing):
        resp = client.post("/api/config", json={
            "description_templates": {"en_short": ""}
        })
    assert resp.status_code == 200
    assert resp.json["description_templates"]["en_short"] == ""


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"DCS" in resp.data


# ── POST /api/generate_shorts ─────────────────────────────────────────────────

def test_generate_shorts_missing_video_path_returns_400(client):
    resp = client.post("/api/generate_shorts", json={"metadata": {"title": "T"}})
    assert resp.status_code == 400
    assert "video_path" in resp.json["error"]


def test_generate_shorts_missing_metadata_returns_400(client, tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    resp = client.post("/api/generate_shorts", json={"video_path": str(video)})
    assert resp.status_code == 400
    assert "metadata" in resp.json["error"]


def test_generate_shorts_file_not_found_returns_404(client):
    resp = client.post("/api/generate_shorts", json={
        "video_path": "/nonexistent/video.mp4",
        "metadata": {"title": "T"},
    })
    assert resp.status_code == 404


def test_generate_shorts_starts_job_and_returns_job_id(client, tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/generate_shorts", json={
            "video_path": str(video),
            "metadata": {"title": "T", "description": "D", "tags": []},
        })
    assert resp.status_code == 200
    assert "job_id" in resp.json
    assert len(resp.json["job_id"]) == 8


def test_generate_shorts_job_starts_in_running_state(client, tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/generate_shorts", json={
            "video_path": str(video),
            "metadata": {"title": "T", "description": "D", "tags": []},
        })
    job_id = resp.json["job_id"]
    status = client.get(f"/api/status/{job_id}")
    assert status.status_code == 200
    assert status.json["status"] == "running"


def test_generate_shorts_empty_acmi_events_accepted(client, tmp_path):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/generate_shorts", json={
            "video_path": str(video),
            "metadata": {"title": "T", "description": "D", "tags": []},
            "acmi_events": {},
        })
    assert resp.status_code == 200
    assert "job_id" in resp.json


# ── POST /api/upload_shorts_batch ───────────────────────────────────────────────

def test_upload_shorts_batch_invalid_payload_returns_400(client):
    resp = client.post("/api/upload_shorts_batch", json={"clips": []})
    assert resp.status_code == 400
    assert "error" in resp.json


def test_upload_shorts_batch_valid_payload_returns_job_id(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T",
                       "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
    assert resp.status_code == 200
    assert "job_id" in resp.json


def test_upload_shorts_batch_job_starts_with_pending_clips(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
    job_id = resp.json["job_id"]
    status = client.get(f"/api/status/{job_id}")
    assert status.json["status"] == "uploading_batch"
    assert status.json["clips"]["1"]["status"] == "pending"
    assert status.json["clips"]["2"]["status"] == "pending"


# ── _run_shorts_batch (vía el endpoint, con Thread real y upload_video mockeado) ──

def test_run_shorts_batch_uploads_all_clips_in_order(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.get_playlists", return_value=[]), \
         patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
        job_id = resp.json["job_id"]

        import time
        for _ in range(50):
            if client.get(f"/api/status/{job_id}").json["status"] == "done":
                break
            time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["status"] == "done"
    assert status["clips"]["1"]["status"] == "done"
    assert status["clips"]["2"]["status"] == "done"
    assert status["result"] == {"uploaded": 2, "failed": 0}
    assert mock_uv.call_count == 2
    assert mock_uv.call_args_list[0].kwargs["publish_at"] == "2026-06-01T19:00:00Z"
    assert mock_uv.call_args_list[1].kwargs["publish_at"] == "2026-06-04T19:00:00Z"


def test_run_shorts_batch_continues_after_one_clip_fails(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.get_playlists", return_value=[]), \
         patch("youtube_uploader.upload_video",
               side_effect=[Exception("quota exceeded"), upload_result]):
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
        })
        job_id = resp.json["job_id"]

        import time
        for _ in range(50):
            if client.get(f"/api/status/{job_id}").json["status"] == "done":
                break
            time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["clips"]["1"]["status"] == "error"
    assert "quota exceeded" in status["clips"]["1"]["error"]
    assert status["clips"]["2"]["status"] == "done"
    assert status["result"] == {"uploaded": 1, "failed": 1}


def test_run_shorts_batch_always_includes_shorts_playlist(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}
    playlists = [{"id": "SH", "title": "SHORTS"}, {"id": "DW", "title": "DCS World"}]

    with patch("youtube_uploader.get_playlists", return_value=playlists), \
         patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
            "playlist_ids": ["PL_extra"],
        })
        job_id = resp.json["job_id"]

        import time
        for _ in range(50):
            if client.get(f"/api/status/{job_id}").json["status"] == "done":
                break
            time.sleep(0.05)

    mock_uv.assert_called_once()
    called_playlists = mock_uv.call_args.kwargs["playlist_ids"]
    assert "SH" in called_playlists
    assert "PL_extra" in called_playlists
    assert "DW" not in called_playlists


def test_run_shorts_batch_auth_failure_marks_all_clips_error(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")

    with patch("youtube_uploader.get_playlists", side_effect=PermissionError("Not authenticated")):
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
        })
        job_id = resp.json["job_id"]

        import time
        for _ in range(50):
            if client.get(f"/api/status/{job_id}").json["status"] == "error":
                break
            time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["status"] == "error"
    assert status["clips"]["1"]["status"] == "error"


def test_run_shorts_batch_dcs_simulate_skips_get_playlists(client, tmp_path, monkeypatch):
    """DCS_SIMULATE=1 must let the batch run without real OAuth (RF-11): get_playlists()
    is a real API call not gated by DCS_SIMULATE inside upload_video(), so the batch
    orchestration must skip calling it entirely in simulate mode."""
    monkeypatch.setenv("DCS_SIMULATE", "1")
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")

    with patch("youtube_uploader.get_playlists", side_effect=PermissionError("Not authenticated")) as mock_gp:
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
        })
        job_id = resp.json["job_id"]

        import time
        for _ in range(50):
            if client.get(f"/api/status/{job_id}").json["status"] == "done":
                break
            time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["status"] == "done"
    assert status["clips"]["1"]["status"] == "done"
    mock_gp.assert_not_called()


# ── _open_file_dialog (macOS) ──────────────────────────────────────────────────

def _mock_run(returncode, stdout="", stderr=""):
    result = type("Result", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()
    return result


def test_open_file_dialog_mac_does_not_target_finder(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["script"] = cmd[-1]
        return _mock_run(0, stdout="/Users/x/video.mp4\n")

    monkeypatch.setattr(app_module.subprocess, "run", fake_run)

    result = app_module._open_file_dialog("/Users/x")

    assert result == "/Users/x/video.mp4"
    assert "Finder" not in captured["script"]
    assert "choose file" in captured["script"]


def test_open_file_dialog_mac_cancelled_returns_none(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        app_module.subprocess, "run",
        lambda *a, **k: _mock_run(1, stderr="execution error: User canceled. (-128)")
    )

    assert app_module._open_file_dialog("/Users/x") is None


def test_open_file_dialog_mac_real_error_raises_with_message(monkeypatch):
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    monkeypatch.setattr(
        app_module.subprocess, "run",
        lambda *a, **k: _mock_run(1, stderr="execution error: Not authorized. (-1743)")
    )

    with pytest.raises(RuntimeError, match="Not authorized"):
        app_module._open_file_dialog("/Users/x")


def test_browse_endpoint_surfaces_mac_error_to_client(client, monkeypatch):
    monkeypatch.setattr(
        app_module, "_open_file_dialog",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("No se pudo abrir el selector de ficheros: boom"))
    )

    resp = client.get("/api/browse")

    assert resp.status_code == 400
    assert "boom" in resp.json["error"]


# ── GET /api/youtube/pending_videos (FEA-08) ──────────────────────────────────

def test_pending_videos_returns_pending_and_scheduled(client):
    queue = {"pending": [{"video_id": "A"}], "scheduled": [{"video_id": "B", "publish_at": "2999-01-01T18:00:00Z"}]}
    with patch("youtube_uploader.list_pending_videos", return_value=queue):
        resp = client.get("/api/youtube/pending_videos")
    assert resp.status_code == 200
    assert resp.json == queue


def test_pending_videos_not_authenticated_returns_401(client):
    with patch("youtube_uploader.list_pending_videos", side_effect=PermissionError("Not authenticated")):
        resp = client.get("/api/youtube/pending_videos")
    assert resp.status_code == 401
    assert "Not authenticated" in resp.json["error"]


def test_pending_videos_api_failure_returns_502(client):
    with patch("youtube_uploader.list_pending_videos", side_effect=RuntimeError("quotaExceeded")):
        resp = client.get("/api/youtube/pending_videos")
    assert resp.status_code == 502
    assert "quotaExceeded" in resp.json["error"]


# ── POST /api/schedule_videos_batch (FEA-08) ──────────────────────────────────

_FUTURE = "2999-06-01T19:00:00Z"


def _schedule_payload(**overrides):
    payload = {"video_ids": ["V1", "V2", "V3"], "first_publish_at": _FUTURE, "interval_days": 3}
    payload.update(overrides)
    return payload


@pytest.mark.parametrize("overrides, fragment", [
    ({"video_ids": []}, "video_ids"),
    ({"video_ids": [f"V{i}" for i in range(16)]}, "max 15"),
    ({"video_ids": ["V1", "V1"]}, "duplicate"),
    ({"first_publish_at": ""}, "first_publish_at"),
    ({"first_publish_at": "no-es-una-fecha"}, "first_publish_at"),
    ({"first_publish_at": "2020-01-01T00:00:00Z"}, "past"),
    ({"interval_days": 0}, "interval_days"),
    ({"interval_days": "3"}, "interval_days"),
])
def test_schedule_batch_invalid_payload_returns_400(client, overrides, fragment):
    with patch("app.threading.Thread") as mock_thread_cls:
        resp = client.post("/api/schedule_videos_batch", json=_schedule_payload(**overrides))
    assert resp.status_code == 400
    assert fragment in resp.json["error"]
    mock_thread_cls.assert_not_called()


def test_schedule_batch_valid_payload_creates_job_with_pending_videos(client):
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/schedule_videos_batch", json=_schedule_payload())
    assert resp.status_code == 200
    status = client.get(f"/api/status/{resp.json['job_id']}").json
    assert status["status"] == "scheduling_batch"
    assert {v: s["status"] for v, s in status["videos"].items()} == {"V1": "pending", "V2": "pending", "V3": "pending"}


def _wait_done(client, job_id):
    import time
    for _ in range(100):
        if client.get(f"/api/status/{job_id}").json["status"] == "done":
            break
        time.sleep(0.05)
    return client.get(f"/api/status/{job_id}").json


def test_schedule_batch_assigns_staggered_dates_in_list_order(client):
    with patch("youtube_uploader.schedule_video") as mock_sv:
        resp = client.post("/api/schedule_videos_batch", json=_schedule_payload())
        status = _wait_done(client, resp.json["job_id"])

    assert status["result"] == {"scheduled": 3, "failed": 0}
    assert [(c.args[0], c.args[1]) for c in mock_sv.call_args_list] == [
        ("V1", "2999-06-01T19:00:00Z"),
        ("V2", "2999-06-04T19:00:00Z"),
        ("V3", "2999-06-07T19:00:00Z"),
    ]


def test_schedule_batch_continues_after_one_video_fails(client):
    def fake_schedule(video_id, publish_at):
        if video_id == "V2":
            raise RuntimeError("video has been published before")

    with patch("youtube_uploader.schedule_video", side_effect=fake_schedule) as mock_sv:
        resp = client.post("/api/schedule_videos_batch", json=_schedule_payload())
        status = _wait_done(client, resp.json["job_id"])

    assert mock_sv.call_count == 3
    assert status["videos"]["V1"]["status"] == "done"
    assert status["videos"]["V2"] == {"status": "error", "error": "video has been published before"}
    assert status["videos"]["V3"]["status"] == "done"
    assert status["result"] == {"scheduled": 2, "failed": 1}


# ── POST /api/parse_acmi con desfase (BUG-06) ─────────────────────────────────

def _acmi_with_one_kill(tmp_path):
    f = tmp_path / "m.acmi"
    f.write_text("FileType=text/acmi/tacview\nFileVersion=2.2\n0,RecordingTime=2026-10-16T22:14:28Z\n"
                 "#0\nA001,Type=FixedWing+Air+FixedWing,Name=MiG-29,Coalition=Enemies\n#300\n-A001\n",
                 encoding="utf-8")
    return f


def test_parse_acmi_manual_offset_shifts_events(client, tmp_path):
    resp = client.post("/api/parse_acmi", json={"acmi_path": str(_acmi_with_one_kill(tmp_path)),
                                                "video_path": "x.mkv", "offset_s": 100})
    assert resp.status_code == 200
    assert resp.json["events"]["kills"][0]["time_s"] == 200.0
    assert resp.json["offset_s"] == 100.0
    assert resp.json["offset_source"] == "manual"


def test_parse_acmi_auto_offset_from_video_name(client, tmp_path):
    with patch("acmi.acmi_offset_seconds", return_value=60.0):
        resp = client.post("/api/parse_acmi", json={"acmi_path": str(_acmi_with_one_kill(tmp_path)),
                                                    "video_path": "2026-10-17_00-34-43.mkv"})
    assert resp.json["events"]["kills"][0]["time_s"] == 240.0
    assert resp.json["offset_source"] == "auto"


def test_parse_acmi_without_video_or_offset_keeps_acmi_time(client, tmp_path):
    resp = client.post("/api/parse_acmi", json={"acmi_path": str(_acmi_with_one_kill(tmp_path))})
    assert resp.json["events"]["kills"][0]["time_s"] == 300.0
    assert resp.json["offset_source"] == "none"


@pytest.mark.parametrize("bad", ["abc", float("inf"), 10 ** 9])
def test_parse_acmi_invalid_offset_returns_400(client, tmp_path, bad):
    resp = client.post("/api/parse_acmi", json={"acmi_path": str(_acmi_with_one_kill(tmp_path)), "offset_s": bad})
    assert resp.status_code == 400


def test_analyze_forwards_manual_acmi_offset_to_generate_metadata(client, tmp_path, monkeypatch):
    """BUG-06: el desfase manual de la UI debe llegar al análisis (capítulos y contexto de Gemini)."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    acmi_file = tmp_path / "m.acmi"
    acmi_file.write_text("FileType=text/acmi/tacview\n", encoding="utf-8")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")

    _, _, mock_generate, _, _ = _run_analyze_sync(
        client, video, {"acmi_path": str(acmi_file), "acmi_offset_s": 1215}, return_value=None)

    assert mock_generate.call_args.kwargs["acmi_offset_s"] == 1215.0


def test_analyze_invalid_acmi_offset_returns_400(client, tmp_path, monkeypatch):
    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    resp = client.post("/api/analyze", json={"video_path": str(video), "acmi_offset_s": "mucho"})
    assert resp.status_code == 400


# ── POST /api/edit/analyze_cuts y /api/edit/plan_summary (FEA-09, Fase 1a) ─────

def _edit_files(tmp_path):
    video = tmp_path / "2026-10-17_00-34-43.mkv"
    video.write_bytes(b"fake")
    acmi_file = tmp_path / "m.acmi"
    acmi_file.write_text("FileType=text/acmi/tacview\n", encoding="utf-8")
    return video, acmi_file


@pytest.mark.parametrize("payload, status", [
    ({}, 400),
    ({"video_path": "no-existe.mkv", "acmi_path": "x.acmi"}, 404),
])
def test_analyze_cuts_rejects_missing_files(client, payload, status):
    assert client.post("/api/edit/analyze_cuts", json=payload).status_code == status


def test_analyze_cuts_requires_an_acmi_file(client, tmp_path):
    video, _acmi_file = _edit_files(tmp_path)
    assert client.post("/api/edit/analyze_cuts", json={"video_path": str(video)}).status_code == 400
    wrong = tmp_path / "m.txt"
    wrong.write_text("x")
    resp = client.post("/api/edit/analyze_cuts", json={"video_path": str(video), "acmi_path": str(wrong)})
    assert resp.status_code == 400


def test_analyze_cuts_invalid_offset_returns_400(client, tmp_path):
    video, acmi_file = _edit_files(tmp_path)
    resp = client.post("/api/edit/analyze_cuts", json={"video_path": str(video), "acmi_path": str(acmi_file),
                                                       "acmi_offset_s": "mucho"})
    assert resp.status_code == 400


def test_analyze_cuts_job_returns_the_proposed_plan(client, tmp_path):
    video, acmi_file = _edit_files(tmp_path)
    plan = {"segments": [{"start": 10.0, "end": 100.0}], "original_duration": 500.0, "resulting_duration": 400.0,
            "offset_s": 12.5, "fade_s": 0.3}

    with patch("video_edit.analyze_cuts", return_value=plan) as mock_analyze:
        resp = client.post("/api/edit/analyze_cuts", json={"video_path": str(video), "acmi_path": str(acmi_file),
                                                           "acmi_offset_s": 12.5})
        status = _wait_done(client, resp.json["job_id"])

    assert status["result"]["resulting_duration"] == 400.0
    assert mock_analyze.call_args.args[2] == 12.5


def test_analyze_cuts_failure_is_reported_in_the_job(client, tmp_path):
    video, acmi_file = _edit_files(tmp_path)
    with patch("video_edit.analyze_cuts", side_effect=ValueError("No player aircraft")):
        resp = client.post("/api/edit/analyze_cuts", json={"video_path": str(video), "acmi_path": str(acmi_file)})
        import time
        for _ in range(100):
            status = client.get(f"/api/status/{resp.json['job_id']}").json
            if status["status"] != "running":
                break
            time.sleep(0.05)
    assert status["status"] == "error"
    assert "No player aircraft" in status["error"]


def test_analyze_cuts_simulate_mode_skips_real_analysis(client, tmp_path, monkeypatch):
    video, acmi_file = _edit_files(tmp_path)
    monkeypatch.setenv("DCS_SIMULATE", "1")
    with patch("video_edit.analyze_cuts", side_effect=AssertionError("must not run in simulate mode")):
        resp = client.post("/api/edit/analyze_cuts", json={"video_path": str(video), "acmi_path": str(acmi_file)})
        status = _wait_done(client, resp.json["job_id"])
    assert status["status"] == "done"
    assert status["result"]["segments"]


def test_plan_summary_returns_totals_and_per_segment_speed(client):
    resp = client.post("/api/edit/plan_summary", json={
        "video_duration": 1000, "fade_s": 0,
        "segments": [{"start": 100, "end": 400, "action": "speed", "fase": "navegacion"}]})
    assert resp.status_code == 200
    assert resp.json["resulting_duration"] == pytest.approx(720.0)
    assert resp.json["segments"][0]["factor"] == pytest.approx(15.0)


@pytest.mark.parametrize("payload", [
    {"video_duration": 1000, "segments": [{"start": 10, "end": 5, "action": "cut"}]},
    {"video_duration": 1000, "segments": [{"start": 0, "end": 10, "action": "speed", "speed": 0.1}]},
    {"video_duration": 0, "segments": []},
    {"video_duration": "x", "segments": []},
    {"video_duration": 1000, "segments": "no"},
    {"video_duration": 1000, "segments": [{"start": 0, "end": 1, "action": "cut"}] * 201},
    {"video_duration": 1000, "segments": [], "fade_s": 99},
])
def test_plan_summary_rejects_invalid_payloads(client, payload):
    assert client.post("/api/edit/plan_summary", json=payload).status_code == 400


# ── POST /api/edit/render y claves de configuración (FEA-09, Fase 1b) ──────────

_RENDER_SEGMENTS = [{"start": 10, "end": 100, "action": "speed", "fase": "rodaje"}]


def _render_video(tmp_path):
    video = tmp_path / "rec.mkv"
    video.write_bytes(b"fake")
    return video


@pytest.mark.parametrize("payload, status", [
    ({}, 400),
    ({"video_path": "no-existe.mkv", "segments": _RENDER_SEGMENTS}, 404),
])
def test_render_rejects_missing_video(client, payload, status):
    assert client.post("/api/edit/render", json=payload).status_code == status


@pytest.mark.parametrize("extra", [
    {"segments": "no"},
    {"segments": []},
    {"segments": [{"start": 0, "end": 1, "action": "cut"}] * 201},
    {"segments": _RENDER_SEGMENTS, "fade_s": 99},
])
def test_render_rejects_invalid_payloads(client, tmp_path, extra):
    resp = client.post("/api/edit/render", json={"video_path": str(_render_video(tmp_path)), **extra})
    assert resp.status_code == 400


def test_render_rejects_segments_outside_the_real_video_duration(client, tmp_path):
    video = _render_video(tmp_path)
    with patch("dcs_meta._get_video_duration", return_value=50.0):
        resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS})
    assert resp.status_code == 400
    assert "outside the video" in resp.json["error"]


def test_render_job_passes_config_and_reports_progress(client, tmp_path):
    video = _render_video(tmp_path)
    seen = {}

    def fake_render(video_path, segments, out_dir, **kwargs):
        seen.update(kwargs, video=video_path, segments=segments, out_dir=out_dir)
        kwargs["on_progress"](40, "Rendering video 1/1")
        return {"output_path": str(tmp_path / "rec_editado.mp4"), "duration": 99.0, "warnings": ["w"],
                "encoder": "libx264", "chunks": 1}

    cfg = {**dcs_meta.DEFAULT_CONFIG, "music_folder": "D:/music", "edit_cq": 30}
    with patch("dcs_meta._get_video_duration", return_value=500.0), \
         patch("dcs_meta.load_config", return_value=cfg), \
         patch("video_render.render_edit", side_effect=fake_render):
        resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS,
                                                     "fade_s": 0})
        status = _wait_done(client, resp.json["job_id"])

    assert status["result"]["output_name"] == "rec_editado.mp4"
    assert status["result"]["warnings"] == ["w"]
    assert seen["cq"] == 30 and seen["music_folder"] == "D:/music" and seen["fade_s"] == 0.0
    assert seen["out_dir"].name == "edits"


def test_render_failure_is_reported_in_the_job(client, tmp_path):
    video = _render_video(tmp_path)
    with patch("dcs_meta._get_video_duration", return_value=500.0), \
         patch("video_render.render_edit", side_effect=RuntimeError("ffmpeg failed: boom")):
        resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS})
        import time
        for _ in range(100):
            status = client.get(f"/api/status/{resp.json['job_id']}").json
            if status["status"] != "running":
                break
            time.sleep(0.05)
    assert status["status"] == "error" and "boom" in status["error"]


def test_render_refuses_a_second_render_while_one_is_running(client, tmp_path):
    video = _render_video(tmp_path)
    assert app_module._render_lock.acquire(blocking=False)
    try:
        with patch("dcs_meta._get_video_duration", return_value=500.0):
            resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS})
    finally:
        app_module._render_lock.release()
    assert resp.status_code == 409


def test_render_releases_the_lock_after_the_job_finishes(client, tmp_path):
    video = _render_video(tmp_path)
    with patch("dcs_meta._get_video_duration", return_value=500.0), \
         patch("video_render.render_edit", return_value={"output_path": "x.mp4", "duration": 1.0, "warnings": [],
                                                         "encoder": "libx264", "chunks": 1}):
        resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS})
        _wait_done(client, resp.json["job_id"])
    assert app_module._render_lock.acquire(blocking=False)
    app_module._render_lock.release()


def test_render_simulate_mode_skips_ffmpeg(client, tmp_path, monkeypatch):
    video = _render_video(tmp_path)
    monkeypatch.setenv("DCS_SIMULATE", "1")
    with patch("video_render.render_edit", side_effect=AssertionError("must not run in simulate mode")):
        resp = client.post("/api/edit/render", json={"video_path": str(video), "segments": _RENDER_SEGMENTS})
        status = _wait_done(client, resp.json["job_id"])
    assert status["status"] == "done" and status["result"]["simulated"] is True


@pytest.mark.parametrize("payload", [{"edit_cq": 5}, {"edit_cq": "x"}, {"music_folder": "Z:/no/existe/nunca"},
                                     {"music_folder": 7}])
def test_config_rejects_invalid_edit_settings(client, payload):
    assert client.post("/api/config", json=payload).status_code == 400


def test_config_accepts_a_music_folder_that_exists(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    resp = client.post("/api/config", json={"music_folder": str(tmp_path), "edit_cq": 26})
    assert resp.status_code == 200
    assert resp.json["music_folder"] == str(tmp_path) and resp.json["edit_cq"] == 26
