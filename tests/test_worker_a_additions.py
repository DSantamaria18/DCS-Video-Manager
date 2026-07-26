"""Tests for Worker A additions: #42, #43, #38, #19, #37, #31, #16, #28."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure the web app and root modules are importable
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "web"))

from app import _suggest_playlist_ids

import dcs_meta

# ── #42 _suggest_playlist_ids aircraft aliases ────────────────────────────────

def test_suggest_playlist_fa18c_matches_hornet_playlist():
    metadata = {"aircraft": "F/A-18C Hornet", "mission_type": "BVR", "campaign": ""}
    playlists = [{"id": "pl1", "title": "Hornet Pilot DCS"}]
    assert "pl1" in _suggest_playlist_ids(metadata, playlists)


def test_suggest_playlist_fa18c_matches_fa18_token():
    metadata = {"aircraft": "F/A-18C Hornet", "mission_type": "", "campaign": ""}
    playlists = [{"id": "pl1", "title": "FA-18 Tutorial"}]
    assert "pl1" in _suggest_playlist_ids(metadata, playlists)


def test_suggest_playlist_f16c_matches_viper():
    metadata = {"aircraft": "F-16C Viper", "mission_type": "", "campaign": ""}
    playlists = [{"id": "pl1", "title": "Viper BFM Guide"}]
    assert "pl1" in _suggest_playlist_ids(metadata, playlists)


def test_suggest_playlist_f14_matches_tomcat():
    metadata = {"aircraft": "F-14 Tomcat", "mission_type": "", "campaign": ""}
    playlists = [{"id": "pl1", "title": "Tomcat BVR Intercept"}]
    assert "pl1" in _suggest_playlist_ids(metadata, playlists)


def test_suggest_playlist_no_false_positive():
    metadata = {"aircraft": "F/A-18C Hornet", "mission_type": "", "campaign": ""}
    playlists = [{"id": "pl1", "title": "Apache Attack Helicopter"}]
    assert "pl1" not in _suggest_playlist_ids(metadata, playlists)


def test_suggest_playlist_empty_metadata_returns_empty():
    metadata = {"aircraft": "", "mission_type": "", "campaign": ""}
    playlists = [{"id": "pl1", "title": "Hornet"}]
    assert _suggest_playlist_ids(metadata, playlists) == []


# ── #43 parse_acmi_events expanded detection ──────────────────────────────────

def _write_acmi(tmp_path, lines):
    p = tmp_path / "test.acmi"
    p.write_text(
        "FileType=text/acmi/tacview\nFileVersion=2.2\n" + "\n".join(lines),
        encoding="utf-8",
    )
    return p


def test_parse_acmi_ir_missile_detected(tmp_path):
    lines = [
        "#1.0",
        "100,T=0|0|100,Name=AIM-9X,Coalition=Allies,Type=Weapon+Missile",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result.get("ir_launches", [])) == 1
    assert result["ir_launches"][0]["name"] == "AIM-9X"


def test_parse_acmi_guided_bomb_detected(tmp_path):
    lines = [
        "#5.0",
        "200,T=0|0|500,Name=GBU-12,Coalition=Allies,Type=Weapon+Bomb",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result.get("bomb_releases", [])) == 1


def test_parse_acmi_friendly_loss_detected(tmp_path):
    lines = [
        "#10.0",
        "300,T=0|0|5000,Name=F/A-18C,Coalition=Allies,Type=Air+FixedWing",
        "#11.0",
        "-300",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result.get("friendly_losses", [])) == 1


def test_parse_acmi_ejection_detected(tmp_path):
    lines = [
        "#15.0",
        "400,T=0|0|100,Name=Pilot,Coalition=Allies,Type=Misc+Human,Tags=Pilot",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert len(result.get("ejection_events", [])) == 1


def test_parse_acmi_events_text_includes_ir(tmp_path):
    lines = [
        "#1.0",
        "100,T=0|0|100,Name=AIM-9M,Coalition=Allies,Type=Weapon+Missile",
    ]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    assert "IR missile" in result.get("events_text", "")


def test_parse_acmi_result_has_new_keys(tmp_path):
    lines = ["#1.0"]
    result = dcs_meta.parse_acmi_events(_write_acmi(tmp_path, lines))
    for key in ("ir_launches", "bomb_releases", "friendly_losses", "ejection_events"):
        assert key in result


# ── #38 build_fallback_metadata ───────────────────────────────────────────────

def test_build_fallback_includes_dcs_world(tmp_path):
    video = tmp_path / "mission_fa18.mp4"
    video.write_bytes(b"fake")
    result = dcs_meta.build_fallback_metadata(video, "", dcs_meta.DEFAULT_CONFIG)
    assert "DCS World" in result["title"]


def test_build_fallback_detects_aircraft_from_context(tmp_path):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    result = dcs_meta.build_fallback_metadata(video, "hornet cas mission", dcs_meta.DEFAULT_CONFIG)
    assert result["aircraft"] == "F/A-18C Hornet"


def test_build_fallback_returns_valid_structure(tmp_path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    result = dcs_meta.build_fallback_metadata(video, "", dcs_meta.DEFAULT_CONFIG)
    for key in ("title", "description", "tags", "chapters", "language", "aircraft", "map"):
        assert key in result


def test_build_fallback_includes_base_tags(tmp_path):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    result = dcs_meta.build_fallback_metadata(video, "", dcs_meta.DEFAULT_CONFIG)
    assert "dcs world" in result["tags"]


def test_build_fallback_no_gemini_error_when_used(tmp_path, monkeypatch):
    video = tmp_path / "x.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "extract_frames", lambda *a, **k: [])
    result = dcs_meta.build_fallback_metadata(video, "", dcs_meta.DEFAULT_CONFIG)
    assert isinstance(result, dict)


# ── #38 app analyze endpoint with Gemini failure ─────────────────────────────

def test_analyze_uses_fallback_on_gemini_failure(monkeypatch, tmp_path):
    from app import app as flask_app
    flask_app.config["TESTING"] = True

    video = tmp_path / "test.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setattr(dcs_meta, "extract_frames", lambda *a, **k: ["base64frame"])
    monkeypatch.setattr(dcs_meta, "generate_metadata", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("quota exceeded")))
    monkeypatch.setattr(dcs_meta, "save_output", lambda *a, **k: (tmp_path / "out.txt", tmp_path / "out.json"))
    monkeypatch.setattr(dcs_meta, "update_memory", lambda *a, **k: None)

    with flask_app.test_client() as client:
        resp = client.post("/api/analyze", json={"video_path": str(video)})
        assert resp.status_code == 200
        job_id = resp.json["job_id"]

        import time
        for _ in range(20):
            time.sleep(0.05)
            status = client.get(f"/api/status/{job_id}").json
            if status["status"] in ("done", "error"):
                break

        assert status["status"] == "done"
        assert status["result"].get("fallback_warning") is not None


# ── #19 check_duplicate ───────────────────────────────────────────────────────

def test_check_duplicate_exact_match():
    metadata = {"aircraft": "F/A-18C Hornet", "map": "Caucasus", "mission_type": "BVR"}
    history = {"videos": [{"aircraft": "F/A-18C Hornet", "map": "Caucasus",
                            "mission_type": "BVR", "title": "DCS | Hornet BVR"}]}
    result = dcs_meta.check_duplicate(metadata, history)
    assert result["similarity"] == 1.0
    assert result["is_duplicate"] is True


def test_check_duplicate_no_match():
    metadata = {"aircraft": "F/A-18C Hornet", "map": "Caucasus", "mission_type": "BVR"}
    history = {"videos": [{"aircraft": "A-10C Warthog", "map": "Persian Gulf",
                            "mission_type": "CAS", "title": "A-10C CAS"}]}
    result = dcs_meta.check_duplicate(metadata, history)
    assert result["is_duplicate"] is False


def test_check_duplicate_empty_history():
    metadata = {"aircraft": "F/A-18C Hornet", "map": "Caucasus", "mission_type": "BVR"}
    result = dcs_meta.check_duplicate(metadata, {"videos": []})
    assert result["is_duplicate"] is False
    assert result["similarity"] == 0.0


def test_check_duplicate_returns_diff():
    metadata = {"aircraft": "F/A-18C Hornet", "map": "Syria", "mission_type": "BVR"}
    history = {"videos": [{"aircraft": "F/A-18C Hornet", "map": "Caucasus",
                            "mission_type": "BVR", "title": "Hornet BVR"}]}
    result = dcs_meta.check_duplicate(metadata, history)
    assert "diff" in result
    assert isinstance(result["diff"], str)


# ── #37 run_upload_checklist ──────────────────────────────────────────────────

def test_checklist_ok_metadata():
    meta = {
        "title": "DCS World | F/A-18C Hornet | BVR Mission Over Caucasus",
        "description": "A" * 350,
        "tags": ["dcs"] * 10,
        "aircraft": "F/A-18C Hornet",
        "chapters": [],
    }
    checks = dcs_meta.run_upload_checklist(meta, dcs_meta.DEFAULT_CONFIG)
    statuses = {c["rule"]: c["status"] for c in checks}
    assert statuses.get("Description length") == "ok"


def test_checklist_short_description_is_fail():
    meta = {
        "title": "DCS World | Hornet | BVR",
        "description": "Short",
        "tags": ["dcs"] * 10,
        "aircraft": "F/A-18C Hornet",
        "chapters": [],
    }
    checks = dcs_meta.run_upload_checklist(meta, dcs_meta.DEFAULT_CONFIG)
    statuses = {c["rule"]: c["status"] for c in checks}
    assert statuses.get("Description length") == "fail"


def test_checklist_returns_list_of_dicts():
    meta = {"title": "T", "description": "D", "tags": [], "aircraft": "", "chapters": []}
    checks = dcs_meta.run_upload_checklist(meta, dcs_meta.DEFAULT_CONFIG)
    assert isinstance(checks, list)
    for item in checks:
        assert "rule" in item and "status" in item and "message" in item


def test_checklist_missing_dcs_world_is_fail():
    meta = {
        "title": "F/A-18C Hornet BVR",
        "description": "A" * 350,
        "tags": ["dcs"] * 10,
        "aircraft": "F/A-18C Hornet",
        "chapters": [],
    }
    checks = dcs_meta.run_upload_checklist(meta, dcs_meta.DEFAULT_CONFIG)
    statuses = {c["rule"]: c["status"] for c in checks}
    assert statuses.get('"DCS World" present') == "fail"


# ── #31 extract_obs_metadata ──────────────────────────────────────────────────

def test_extract_obs_metadata_returns_dict_structure(tmp_path, monkeypatch):
    video = tmp_path / "test.mkv"
    video.write_bytes(b"fake")
    import subprocess as _sp

    class _MockResult:
        returncode = 0
        stdout = '{"format":{"tags":{}},"chapters":[]}'

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _MockResult())
    result = dcs_meta.extract_obs_metadata(video)
    assert "obs_description" in result
    assert "chapters" in result
    assert isinstance(result["chapters"], list)


def test_extract_obs_metadata_reads_description_tag(tmp_path, monkeypatch):
    video = tmp_path / "test.mkv"
    video.write_bytes(b"fake")
    import subprocess as _sp

    class _MockResult:
        returncode = 0
        stdout = json.dumps({
            "format": {"tags": {"DESCRIPTION": "Briefing|Combat|RTB"}},
            "chapters": [],
        })

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _MockResult())
    result = dcs_meta.extract_obs_metadata(video)
    assert result["obs_description"] == "Briefing|Combat|RTB"


def test_extract_obs_metadata_reads_chapters(tmp_path, monkeypatch):
    video = tmp_path / "test.mkv"
    video.write_bytes(b"fake")
    import subprocess as _sp

    class _MockResult:
        returncode = 0
        stdout = json.dumps({
            "format": {"tags": {}},
            "chapters": [
                {"start_time": "0.0", "tags": {"title": "Briefing"}},
                {"start_time": "90.0", "tags": {"title": "Takeoff"}},
            ],
        })

    monkeypatch.setattr(_sp, "run", lambda *a, **k: _MockResult())
    result = dcs_meta.extract_obs_metadata(video)
    assert len(result["chapters"]) == 2
    assert result["chapters"][0]["title"] == "Briefing"
    assert result["chapters"][1]["time"] == "1:30"


# ── #16 upload_video publish_at ───────────────────────────────────────────────

def test_upload_video_publish_at_sets_private_and_publishAt(monkeypatch):
    import youtube_uploader as yu
    captured = {}

    def _mock_do_insert(youtube, body, video_path, progress_callback=None):
        captured["body"] = body
        return {"id": "vid123"}

    monkeypatch.setattr(yu, "_build_service", lambda: None)
    monkeypatch.setattr(yu, "_do_insert", _mock_do_insert)
    monkeypatch.setattr(yu, "_sanitize_tags", lambda t: t)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake")
        fp = f.name
    try:
        yu.upload_video(fp, "T", "D", [], publish_at="2026-06-01T19:00:00Z")
    except Exception:  # noqa: BLE001 — solo interesa el cuerpo capturado antes de _do_insert; lo posterior no está mockeado a propósito
        pass
    finally:
        os.unlink(fp)

    assert "body" in captured
    assert captured["body"]["status"]["privacyStatus"] == "private"
    assert captured["body"]["status"].get("publishAt") == "2026-06-01T19:00:00Z"


def test_upload_video_no_publish_at_uses_requested_privacy(monkeypatch):
    import youtube_uploader as yu
    captured = {}

    def _mock_do_insert(youtube, body, video_path, progress_callback=None):
        captured["body"] = body
        return {"id": "vid456"}

    monkeypatch.setattr(yu, "_build_service", lambda: None)
    monkeypatch.setattr(yu, "_do_insert", _mock_do_insert)
    monkeypatch.setattr(yu, "_sanitize_tags", lambda t: t)

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"fake")
        fp = f.name
    try:
        yu.upload_video(fp, "T", "D", [], privacy="public")
    except Exception:  # noqa: BLE001 — solo interesa el cuerpo capturado antes de _do_insert; lo posterior no está mockeado a propósito
        pass
    finally:
        os.unlink(fp)

    assert "body" in captured
    assert captured["body"]["status"]["privacyStatus"] == "public"
    assert "publishAt" not in captured["body"]["status"]


# ── #28 export_history_csv endpoint ──────────────────────────────────────────

def test_export_history_csv_returns_csv(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    videos = [
        {"date": "2026-05-01", "filename": "v1.mkv", "aircraft": "F/A-18C Hornet",
         "map": "Caucasus", "mission_type": "BVR", "title": "Test", "video_id": "abc"},
    ]
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": videos})
    with flask_app.test_client() as client:
        resp = client.get("/api/export_history_csv")
    assert resp.status_code == 200
    assert b"F/A-18C Hornet" in resp.data
    assert b"Caucasus" in resp.data


def test_export_history_csv_has_headers(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": []})
    with flask_app.test_client() as client:
        resp = client.get("/api/export_history_csv")
    assert b"aircraft" in resp.data
    assert b"mission_type" in resp.data


# ── #33 / app config recordings_folder ───────────────────────────────────────

def test_default_config_has_recordings_folder():
    assert "recordings_folder" in dcs_meta.DEFAULT_CONFIG


# ── batch endpoints ───────────────────────────────────────────────────────────

def test_batch_start_requires_folder_configured(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    monkeypatch.setattr(dcs_meta, "load_config", lambda: {**dcs_meta.DEFAULT_CONFIG, "recordings_folder": ""})
    with flask_app.test_client() as client:
        resp = client.post("/api/batch/start")
    assert resp.status_code == 400


def test_batch_status_returns_running_field(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        resp = client.get("/api/batch/status")
    assert resp.status_code == 200
    assert "running" in resp.json


# ── #34 narration endpoint ────────────────────────────────────────────────────

def test_narration_endpoint_missing_data(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        resp = client.post("/api/narration", json={})
    assert resp.status_code == 400


def test_narration_endpoint_file_not_found(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        resp = client.post("/api/narration", json={
            "video_path": "/nonexistent/video.mp4",
            "metadata": {"title": "T"},
        })
    assert resp.status_code == 404


# ── #check_duplicate endpoint ─────────────────────────────────────────────────

def test_check_duplicate_endpoint(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    monkeypatch.setattr(dcs_meta, "load_memory", lambda: {"videos": []})
    with flask_app.test_client() as client:
        resp = client.post("/api/check_duplicate", json={
            "metadata": {"aircraft": "F/A-18C", "map": "Caucasus", "mission_type": "BVR"},
        })
    assert resp.status_code == 200
    assert "is_duplicate" in resp.json


# ── #upload_checklist endpoint ────────────────────────────────────────────────

def test_upload_checklist_endpoint(monkeypatch):
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        resp = client.post("/api/upload_checklist", json={
            "metadata": {
                "title": "DCS World | Hornet | BVR",
                "description": "A" * 400,
                "tags": ["dcs"] * 10,
                "aircraft": "F/A-18C Hornet",
                "chapters": [],
            },
        })
    assert resp.status_code == 200
    assert "checklist" in resp.json
    assert isinstance(resp.json["checklist"], list)
