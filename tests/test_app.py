import os
import pytest
from unittest.mock import patch
from app import app as flask_app
import app as app_module
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
    resp = client.post("/api/analyze", json={"video_path": str(video)})
    assert resp.status_code == 200
    assert "job_id" in resp.json
    assert len(resp.json["job_id"]) == 8


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
        resp = client.post("/api/upload_youtube", json={
            "video_path": "/fake/video.mp4",
            "metadata": {"title": "T", "description": "D", "tags": []},
            "thumbnail_url": "/output/nonexistent_thumb.jpg"
        })

    # upload_video should have been called with thumbnail_path=None
    mock_uv.assert_called_once()
    assert mock_uv.call_args.kwargs.get("thumbnail_path") is None


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


def test_post_config_all_valid_gemini_models_accepted(client, tmp_path, monkeypatch):
    monkeypatch.setattr(dcs_meta, "CONFIG_PATH", tmp_path / "config.json")
    for model in ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"):
        payload = {**VALID_CONFIG_PAYLOAD, "model": model}
        with patch("dcs_meta.load_config", return_value=dict(VALID_CONFIG_PAYLOAD)):
            resp = client.post("/api/config", json=payload)
        assert resp.status_code == 200, f"Expected 200 for model {model}"


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


def test_suggest_playlists_no_match_returns_empty(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "UH-1H Huey", "mission_type": "Transport", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert resp.json["suggested"] == []


def test_suggest_playlists_multiple_matches(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "A-10C Warthog", "mission_type": "CAS", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    suggested = resp.json["suggested"]
    assert "PL3" in suggested


def test_suggest_playlists_empty_metadata_returns_empty(client):
    resp = client.post("/api/suggest_playlists", json={
        "metadata": {"aircraft": "", "mission_type": "", "campaign": ""},
        "playlists": PLAYLISTS,
    })
    assert resp.status_code == 200
    assert resp.json["suggested"] == []


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


def test_suggest_playlist_ids_empty_playlists():
    from app import _suggest_playlist_ids
    assert _suggest_playlist_ids({"aircraft": "Hornet"}, []) == []


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
