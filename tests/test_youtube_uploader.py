"""Tests for youtube_uploader — thumbnail upload behaviour."""

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_youtube_mock(video_id="ABC123"):
    """Return a mock youtube service. Tests must set insert_req.next_chunk.side_effect."""
    insert_req = MagicMock()

    videos = MagicMock()
    videos.return_value.insert.return_value = insert_req

    thumbnails_req = MagicMock()
    thumbnails_req.execute.return_value = {}
    thumbnails = MagicMock()
    thumbnails.return_value.set.return_value = thumbnails_req

    playlist_req = MagicMock()
    playlist_req.execute.return_value = {}
    playlist_items = MagicMock()
    playlist_items.return_value.insert.return_value = playlist_req

    svc = MagicMock()
    svc.videos = videos
    svc.thumbnails = thumbnails
    svc.playlistItems = playlist_items
    return svc


# ---------------------------------------------------------------------------
# _upload_thumbnail
# ---------------------------------------------------------------------------

def test_upload_thumbnail_calls_thumbnails_set(tmp_path):
    """_upload_thumbnail must call thumbnails().set() with correct videoId and media."""

    from youtube_uploader import _upload_thumbnail

    img = tmp_path / "thumb.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)  # minimal fake JPEG header

    svc = _make_youtube_mock()
    _upload_thumbnail(svc, "VIDEO123", str(img))

    svc.thumbnails.return_value.set.assert_called_once()
    kwargs = svc.thumbnails.return_value.set.call_args
    assert kwargs.kwargs.get("videoId") == "VIDEO123" or kwargs[1].get("videoId") == "VIDEO123"


# ---------------------------------------------------------------------------
# upload_video — thumbnail_path integration
# ---------------------------------------------------------------------------

def test_upload_video_sets_thumbnail_when_path_provided(tmp_path):
    """upload_video result must include thumbnail_set=True when thumbnail_path is given."""
    from youtube_uploader import upload_video

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake_video")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    svc = _make_youtube_mock("VID_OK")
    # Fix next_chunk to return on first call
    svc.videos.return_value.insert.return_value.next_chunk.side_effect = [
        (None, {"id": "VID_OK"})
    ]

    with patch("youtube_uploader._build_service", return_value=svc):
        result = upload_video(
            video_path=str(video),
            title="Test",
            description="Desc",
            tags=[],
            thumbnail_path=str(thumb),
        )

    assert result["video_id"] == "VID_OK"
    assert result.get("thumbnail_set") is True


def test_upload_video_thumbnail_failure_is_non_fatal(tmp_path):
    """A failing thumbnails.set call must not abort the upload."""
    from youtube_uploader import upload_video

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake_video")
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)

    svc = _make_youtube_mock("VID_FAIL_THUMB")
    svc.videos.return_value.insert.return_value.next_chunk.side_effect = [
        (None, {"id": "VID_FAIL_THUMB"})
    ]
    # Make thumbnails.set raise an error
    svc.thumbnails.return_value.set.return_value.execute.side_effect = Exception("quota exceeded")

    with patch("youtube_uploader._build_service", return_value=svc):
        result = upload_video(
            video_path=str(video),
            title="Test",
            description="Desc",
            tags=[],
            thumbnail_path=str(thumb),
        )

    # Upload succeeded, thumbnail failed gracefully
    assert result["video_id"] == "VID_FAIL_THUMB"
    assert result.get("thumbnail_set") is False
    assert "thumbnail_warning" in result


def test_upload_video_no_thumbnail_path_skips_set(tmp_path):
    """upload_video must not call thumbnails().set() when thumbnail_path is None."""
    from youtube_uploader import upload_video

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake_video")

    svc = _make_youtube_mock("VID_NO_THUMB")
    svc.videos.return_value.insert.return_value.next_chunk.side_effect = [
        (None, {"id": "VID_NO_THUMB"})
    ]

    with patch("youtube_uploader._build_service", return_value=svc):
        result = upload_video(
            video_path=str(video),
            title="Test",
            description="Desc",
            tags=[],
            thumbnail_path=None,
        )

    assert result["video_id"] == "VID_NO_THUMB"
    assert "thumbnail_set" not in result
    svc.thumbnails.return_value.set.assert_not_called()


# ---------------------------------------------------------------------------
# upload_video — DCS_SIMULATE mode (FEA-04)
# ---------------------------------------------------------------------------

def test_upload_video_simulate_mode_skips_service(tmp_path, monkeypatch):
    """DCS_SIMULATE=1 must return a canned result without touching _build_service."""
    from youtube_uploader import upload_video

    video = tmp_path / "vid.mp4"
    video.write_bytes(b"fake_video")

    monkeypatch.setenv("DCS_SIMULATE", "1")

    def _fail_if_called():
        raise AssertionError("_build_service must not be called in simulate mode")

    with patch("youtube_uploader._build_service", side_effect=_fail_if_called):
        result = upload_video(
            video_path=str(video),
            title="Test",
            description="Desc",
            tags=["dcs", "hornet"],
        )

    assert result["status"] == "simulated"
    assert result["video_id"].startswith("SIMULATED")
    assert result["url"].endswith(result["video_id"])
    assert result["playlists_added"] == []


# ---------------------------------------------------------------------------
# list_pending_videos / schedule_video (FEA-08)
# ---------------------------------------------------------------------------

def _video_item(vid, *, privacy="private", publish_at=None, uploaded="2026-10-01T10:00:00Z",
                duration="PT45M10S", title=None):
    status = {"privacyStatus": privacy, "embeddable": True, "license": "youtube",
              "publicStatsViewable": False}
    if publish_at:
        status["publishAt"] = publish_at
    return {
        "id": vid,
        "snippet": {"title": title or f"Titulo {vid}", "publishedAt": uploaded,
                    "thumbnails": {"medium": {"url": f"https://img/{vid}.jpg"}}},
        "status": status,
        "contentDetails": {"duration": duration},
    }


def _listing_service(items, page_size=50):
    """Mock service whose uploads playlist holds `items` (newest first) across pages of `page_size`."""
    by_id = {it["id"]: it for it in items}
    ids = [it["id"] for it in items]
    svc = MagicMock()
    svc.channels.return_value.list.return_value.execute.return_value = {
        "items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU_UPLOADS"}}}]
    }

    def playlist_list(**kw):
        start = int(kw.get("pageToken") or 0)
        chunk = ids[start:start + page_size]
        resp = {"items": [{"contentDetails": {"videoId": v}} for v in chunk]}
        if start + page_size < len(ids):
            resp["nextPageToken"] = str(start + page_size)
        req = MagicMock()
        req.execute.return_value = resp
        return req

    def videos_list(**kw):
        req = MagicMock()
        req.execute.return_value = {"items": [by_id[v] for v in kw["id"].split(",") if v in by_id]}
        return req

    svc.playlistItems.return_value.list.side_effect = playlist_list
    svc.videos.return_value.list.side_effect = videos_list
    return svc


def test_list_pending_videos_splits_pending_scheduled_and_ignores_public():
    from youtube_uploader import list_pending_videos

    svc = _listing_service([
        _video_item("PUB", privacy="public"),
        _video_item("SCH", publish_at="2999-01-01T18:00:00Z"),
        _video_item("PEN"),
    ])
    with patch("youtube_uploader._build_service", return_value=svc):
        result = list_pending_videos()

    assert [v["video_id"] for v in result["pending"]] == ["PEN"]
    assert [v["video_id"] for v in result["scheduled"]] == ["SCH"]
    assert result["scheduled"][0]["publish_at"] == "2999-01-01T18:00:00Z"


def test_list_pending_videos_orders_oldest_first_and_flags_shorts():
    from youtube_uploader import list_pending_videos

    svc = _listing_service([  # la playlist de subidas viene con lo más nuevo primero
        _video_item("NEW", uploaded="2026-10-10T10:00:00Z", duration="PT45S"),
        _video_item("OLD", uploaded="2026-09-01T10:00:00Z", duration="PT1H2M3S"),
    ])
    with patch("youtube_uploader._build_service", return_value=svc):
        pending = list_pending_videos()["pending"]

    assert [v["video_id"] for v in pending] == ["OLD", "NEW"]
    assert pending[0]["duration_sec"] == 3723 and pending[0]["is_short"] is False
    assert pending[1]["duration_sec"] == 45 and pending[1]["is_short"] is True
    assert pending[0]["thumbnail_url"] == "https://img/OLD.jpg"


def test_list_pending_videos_paginates_and_batches_videos_list_by_50():
    from youtube_uploader import list_pending_videos

    items = [_video_item(f"V{i:03d}", uploaded=f"2026-01-01T10:{i % 60:02d}:00Z") for i in range(120)]
    svc = _listing_service(items, page_size=50)
    with patch("youtube_uploader._build_service", return_value=svc):
        pending = list_pending_videos()["pending"]

    assert len(pending) == 120
    batch_sizes = [len(c.kwargs["id"].split(",")) for c in svc.videos.return_value.list.call_args_list]
    assert batch_sizes == [50, 50, 20]


def test_schedule_video_resends_existing_status_fields():
    """videos.update borra lo que no se reenvía: debe conservar embeddable/license/publicStatsViewable."""
    from youtube_uploader import schedule_video

    svc = _listing_service([_video_item("VID1")])
    with patch("youtube_uploader._build_service", return_value=svc):
        schedule_video("VID1", "2999-01-01T18:00:00Z")

    kwargs = svc.videos.return_value.update.call_args.kwargs
    assert kwargs["part"] == "status"
    assert kwargs["body"]["id"] == "VID1"
    assert kwargs["body"]["status"] == {
        "privacyStatus": "private",
        "publishAt": "2999-01-01T18:00:00Z",
        "embeddable": True,
        "license": "youtube",
        "publicStatsViewable": False,
    }
    svc.videos.return_value.update.return_value.execute.assert_called_once()


def test_schedule_video_unknown_id_raises_lookup_error():
    import pytest

    from youtube_uploader import schedule_video

    svc = _listing_service([])
    with patch("youtube_uploader._build_service", return_value=svc), pytest.raises(LookupError):
        schedule_video("NOPE", "2999-01-01T18:00:00Z")
    svc.videos.return_value.update.assert_not_called()


def test_pending_queue_simulate_mode_skips_service(monkeypatch):
    from youtube_uploader import list_pending_videos, schedule_video

    monkeypatch.setenv("DCS_SIMULATE", "1")

    def _fail_if_called():
        raise AssertionError("_build_service must not be called in simulate mode")

    with patch("youtube_uploader._build_service", side_effect=_fail_if_called):
        result = list_pending_videos()
        scheduled = schedule_video("SIMULATED1", "2999-01-01T18:00:00Z")

    assert result["pending"] and result["scheduled"]
    assert all(v["video_id"].startswith("SIMULATED") for v in result["pending"])
    assert scheduled["status"] == "simulated"
