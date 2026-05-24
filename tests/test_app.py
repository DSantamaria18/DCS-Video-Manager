import os
import pytest
from unittest.mock import patch
from app import app as flask_app


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
    resp = client.post("/api/analyze", json={"video_path": str(video)})
    job_id = resp.json["job_id"]

    status = client.get(f"/api/status/{job_id}")
    assert status.status_code == 200
    assert "status" in status.json
    assert "progress" in status.json


# ── POST /api/upload_youtube ──────────────────────────────────────────────────

def test_upload_youtube_missing_fields_returns_400(client):
    resp = client.post("/api/upload_youtube", json={})
    assert resp.status_code == 400


def test_upload_youtube_missing_metadata_returns_400(client):
    resp = client.post("/api/upload_youtube", json={"video_path": "/some/video.mp4"})
    assert resp.status_code == 400


def test_upload_youtube_no_uploader_returns_500(client):
    resp = client.post("/api/upload_youtube", json={
        "video_path": "/some/video.mp4",
        "metadata": {"title": "Test", "description": "desc", "tags": []}
    })
    assert resp.status_code == 500


# ── GET /api/youtube/status ───────────────────────────────────────────────────

def test_youtube_status_returns_authenticated_key(client):
    resp = client.get("/api/youtube/status")
    assert resp.status_code == 200
    assert "authenticated" in resp.json


# ── GET / ─────────────────────────────────────────────────────────────────────

def test_index_returns_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"DCS" in resp.data
