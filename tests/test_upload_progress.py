"""Tests for Task #3 (upload progress) and Task #40 (analytics tracking)."""

from unittest.mock import MagicMock, patch

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_media_mock(size=1000, progress_values=None):
    """Return a mock MediaFileUpload with controllable _size and resumable_progress."""
    media = MagicMock()
    media._size = size
    # resumable_progress is updated after each chunk; we use a list to simulate progression
    _progress_iter = iter(progress_values or [size])

    def _get_progress():
        try:
            return next(_progress_iter)
        except StopIteration:
            return size

    type(media).resumable_progress = property(lambda self: _get_progress())
    return media


def _make_insert_req(responses):
    """Return a mock insert request whose next_chunk cycles through responses."""
    req = MagicMock()
    req.next_chunk.side_effect = responses
    return req


def _make_youtube_mock(insert_req):
    svc = MagicMock()
    svc.videos.return_value.insert.return_value = insert_req
    return svc


# ── _do_insert progress_callback ─────────────────────────────────────────────

def test_do_insert_calls_progress_callback(tmp_path):
    """_do_insert must invoke progress_callback at least once during upload."""
    from youtube_uploader import _do_insert

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"x" * 1000)

    insert_req = _make_insert_req([(None, None), (None, {"id": "ABC"})])
    svc = _make_youtube_mock(insert_req)

    received = []

    media_mock = MagicMock()
    media_mock._size = 1000
    media_mock.resumable_progress = 500

    with patch("googleapiclient.http.MediaFileUpload", return_value=media_mock), \
         patch("youtube_uploader.MediaFileUpload", return_value=media_mock, create=True):
        _do_insert(svc, {"snippet": {}, "status": {}}, str(video),
                   progress_callback=lambda pct: received.append(pct))

    assert len(received) >= 1


def test_do_insert_no_callback_does_not_raise(tmp_path):
    """_do_insert must work normally when progress_callback is None."""
    from youtube_uploader import _do_insert

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"x" * 100)

    insert_req = _make_insert_req([(None, {"id": "XYZ"})])
    svc = _make_youtube_mock(insert_req)

    media_mock = MagicMock()
    media_mock._size = 100
    media_mock.resumable_progress = 100

    with patch("googleapiclient.http.MediaFileUpload", return_value=media_mock), \
         patch("youtube_uploader.MediaFileUpload", return_value=media_mock, create=True):
        result = _do_insert(svc, {"snippet": {}, "status": {}}, str(video))

    assert result == {"id": "XYZ"}


def test_do_insert_callback_receives_percentage_between_0_and_100(tmp_path):
    """Progress values passed to callback must be in [0, 100]."""
    from youtube_uploader import _do_insert

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"x" * 200)

    insert_req = _make_insert_req([
        (None, None),
        (None, {"id": "PQ"})
    ])
    svc = _make_youtube_mock(insert_req)

    received = []

    media_mock = MagicMock()
    media_mock._size = 200
    media_mock.resumable_progress = 100  # 50% after first chunk

    with patch("googleapiclient.http.MediaFileUpload", return_value=media_mock), \
         patch("youtube_uploader.MediaFileUpload", return_value=media_mock, create=True):
        _do_insert(svc, {"snippet": {}, "status": {}}, str(video),
                   progress_callback=lambda pct: received.append(pct))

    for v in received:
        assert 0 <= v <= 100


# ── upload_youtube endpoint — upload_progress in status ──────────────────────

def test_upload_youtube_sets_upload_progress_in_status(tmp_path):
    """upload_youtube() must create a job with upload_progress key set to 0."""
    import app as app_module
    from app import app as flask_app

    flask_app.config["TESTING"] = True

    upload_result = {
        "video_id": "VIDPROG",
        "url": "https://youtu.be/VIDPROG",
        "status": "uploaded",
        "privacy": "private",
        "tags_skipped": False,
        "playlists_added": [],
    }

    with flask_app.test_client() as client:
        # Freeze the background thread so we can inspect status before it runs
        with patch("app.threading.Thread") as mock_thread_cls:
            mock_thread_cls.return_value.start.return_value = None
            resp = client.post("/api/upload_youtube", json={
                "video_path": "/fake/video.mp4",
                "metadata": {"title": "T", "description": "D", "tags": []},
            })

        assert resp.status_code == 200
        job_id = resp.json["job_id"]
        assert job_id in app_module.processing_status
        entry = app_module.processing_status[job_id]
        assert "upload_progress" in entry
        assert entry["upload_progress"] == 0
        assert entry["status"] == "uploading"


def test_upload_youtube_returns_job_id_not_result_directly(tmp_path):
    """upload_youtube() must return {job_id: ...} (async) instead of the upload result."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        with patch("app.threading.Thread") as mock_thread_cls:
            mock_thread_cls.return_value.start.return_value = None
            resp = client.post("/api/upload_youtube", json={
                "video_path": "/fake/video.mp4",
                "metadata": {"title": "T", "description": "D", "tags": []},
            })

    assert resp.status_code == 200
    assert "job_id" in resp.json
    assert "video_id" not in resp.json  # not the direct result


# ── analytics: build_analytics_service / fetch_video_analytics ───────────────

def test_fetch_video_analytics_returns_dict_on_success():
    """fetch_video_analytics must parse API rows and return the expected keys."""
    from youtube_uploader import fetch_video_analytics

    mock_response = {
        "rows": [["video123", 42, 150, 5]]
    }
    mock_svc = MagicMock()
    mock_svc.reports.return_value.query.return_value.execute.return_value = mock_response

    with patch("youtube_uploader.build_analytics_service", return_value=mock_svc):
        result = fetch_video_analytics("video123")

    assert result["views"] == 42
    assert result["watch_minutes"] == 150
    assert result["likes"] == 5
    assert "fetched_at" in result


def test_fetch_video_analytics_returns_empty_dict_on_error():
    """fetch_video_analytics must return {} when the API raises an exception."""
    from youtube_uploader import fetch_video_analytics

    with patch("youtube_uploader.build_analytics_service", side_effect=Exception("API error")):
        result = fetch_video_analytics("badid")

    assert result == {}


def test_fetch_video_analytics_returns_zeros_when_no_rows():
    """fetch_video_analytics returns zeros (not empty dict) when the API returns no rows."""
    from youtube_uploader import fetch_video_analytics

    mock_response = {"rows": []}
    mock_svc = MagicMock()
    mock_svc.reports.return_value.query.return_value.execute.return_value = mock_response

    with patch("youtube_uploader.build_analytics_service", return_value=mock_svc):
        result = fetch_video_analytics("novid")

    assert result["views"] == 0
    assert result["watch_minutes"] == 0
    assert result["likes"] == 0


# ── schedule_analytics_polling ────────────────────────────────────────────────

def test_schedule_analytics_polling_starts_four_timers():
    """schedule_analytics_polling must create exactly 4 daemon timers (1h,6h,12h,24h)."""
    from youtube_uploader import schedule_analytics_polling

    timers = []

    class FakeTimer:
        def __init__(self, delay, fn):
            self.delay = delay
            self.fn = fn
            self.daemon = False
            timers.append(self)

        def start(self):
            pass

    with patch("youtube_uploader.threading.Timer", FakeTimer):
        schedule_analytics_polling("VID1", "flight.mp4")

    assert len(timers) == 4
    delays = sorted(t.delay for t in timers)
    assert delays == [3600, 21600, 43200, 86400]
    assert all(t.daemon for t in timers)


# ── GET /api/analytics/<video_id> ─────────────────────────────────────────────

def test_analytics_endpoint_returns_empty_for_unknown_video():
    """GET /api/analytics/<id> must return [] when video_id is not in history."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True

    with flask_app.test_client() as client:
        with patch("dcs_meta.load_memory", return_value={"videos": []}), \
             patch("youtube_uploader.fetch_video_analytics", return_value={}):
            resp = client.get("/api/analytics/unknownid")

    assert resp.status_code == 200
    assert resp.json == []


def test_analytics_endpoint_returns_stored_data():
    """GET /api/analytics/<id> must return the stored analytics list from history."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True

    stored = [{"views": 10, "watch_minutes": 5, "likes": 1, "fetched_at": "2026-01-01T00:00:00+00:00"}]
    memory = {"videos": [{"video_id": "KNOWNVID", "analytics": stored}]}

    with flask_app.test_client() as client:
        with patch("dcs_meta.load_memory", return_value=memory):
            resp = client.get("/api/analytics/KNOWNVID")

    assert resp.status_code == 200
    assert resp.json == stored


def test_analytics_endpoint_fetches_on_demand_when_no_stored_data():
    """When video is in history but has no analytics list, endpoint should call fetch."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True

    memory = {"videos": [{"video_id": "NEWVID"}]}  # no 'analytics' key
    on_demand = {"views": 5, "watch_minutes": 2, "likes": 0, "fetched_at": "2026-01-01T00:00:00+00:00"}

    with flask_app.test_client() as client:
        with patch("dcs_meta.load_memory", return_value=memory), \
             patch("youtube_uploader.fetch_video_analytics", return_value=on_demand) as mock_fetch:
            resp = client.get("/api/analytics/NEWVID")

    assert resp.status_code == 200
    assert resp.json == [on_demand]
    mock_fetch.assert_called_once_with("NEWVID")
