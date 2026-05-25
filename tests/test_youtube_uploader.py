"""Tests for youtube_uploader — thumbnail upload behaviour."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, call


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
    from googleapiclient.http import MediaFileUpload

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
