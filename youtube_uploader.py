"""
YouTube uploader — TheCylonPilot DCS Automation
Uses YouTube Data API v3 with OAuth2.
Credential type: Desktop app (InstalledAppFlow)
"""

import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE               = Path(__file__).parent
CLIENT_SECRET_PATH = BASE / "config" / "client_secret.json"
TOKEN_PATH         = BASE / "config" / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly"
]

_auth_state = {"result": None, "done": threading.Event()}


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    """Start the OAuth flow in a background thread (browser opens automatically); call wait_for_auth() to block until done."""
    if not CLIENT_SECRET_PATH.exists():
        raise FileNotFoundError(
            f"client_secret.json not found at {CLIENT_SECRET_PATH}\n"
            "Download it from Google Cloud Console → APIs & Services → Credentials"
        )

    _auth_state["result"] = None
    _auth_state["done"].clear()

    def _do_auth():
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_PATH), SCOPES
            )
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                success_message="Authorization complete. You can close this tab."
            )
            TOKEN_PATH.parent.mkdir(exist_ok=True)
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            _auth_state["result"] = {"ok": True}
        except Exception as e:  # noqa: BLE001 — superficie de googleapiclient no verificable sin credenciales reales; fallo no fatal por diseño
            _auth_state["result"] = {"error": str(e)}
        finally:
            _auth_state["done"].set()

    threading.Thread(target=_do_auth, daemon=True).start()
    return "browser_opened_by_server"


def wait_for_auth() -> dict:
    """Block until OAuth completes (max 3 min). Called by /api/youtube/wait_auth."""
    received = _auth_state["done"].wait(timeout=180)
    if not received:
        return {"error": "Timeout — no response within 3 minutes. Try again."}
    return _auth_state["result"] or {"error": "Unknown error"}


# ── Credentials ───────────────────────────────────────────────────────────────

def _get_credentials():
    """Load OAuth2 credentials from token file and refresh them if expired."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.exists():
        raise PermissionError("Not authenticated. Complete YouTube OAuth setup first.")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _build_service():
    """Build and return an authenticated YouTube Data API v3 service client."""
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_get_credentials())


# ── YouTube API ───────────────────────────────────────────────────────────────

def get_playlists() -> list:
    """Return [{id, title}] for all channel playlists."""
    response = _build_service().playlists().list(
        part="snippet", mine=True, maxResults=50
    ).execute()
    return [
        {"id": item["id"], "title": item["snippet"]["title"]}
        for item in response.get("items", [])
    ]


SHORT_MAX_SECONDS = 180  # etiqueta "Short" de la cola de pendientes; heurística, no criterio de YouTube
# videos.list admite como máximo 50 ids por llamada
_VIDEOS_LIST_BATCH = 50
_ISO_DURATION = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _iso_duration_to_seconds(iso: str) -> int:
    """Convert a YouTube ISO 8601 duration ('PT1H2M3S') to seconds; 0 if unparseable."""
    m = _ISO_DURATION.match(iso or "")
    if not m:
        return 0
    hours, minutes, seconds = (int(g or 0) for g in m.groups())
    return hours * 3600 + minutes * 60 + seconds


def _uploads_video_ids(youtube) -> list:
    """Return every video id in the channel's uploads playlist, newest first."""
    channel = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        page = youtube.playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=50, pageToken=token
        ).execute()
        ids += [it["contentDetails"]["videoId"] for it in page.get("items", [])]
        token = page.get("nextPageToken")
        if not token:
            return ids


def _simulated_pending_queue() -> dict:
    def _item(n, uploaded, duration_sec):
        return {"video_id": f"SIMULATED{n}", "title": f"[SIMULATED] Video {n}", "uploaded_at": uploaded,
                "duration_sec": duration_sec, "thumbnail_url": "", "is_short": duration_sec <= SHORT_MAX_SECONDS}
    return {
        "pending": [_item(1, "2026-09-01T10:00:00Z", 2700), _item(2, "2026-09-05T10:00:00Z", 3100),
                    _item(3, "2026-09-09T10:00:00Z", 45)],
        "scheduled": [{**_item(4, "2026-08-20T10:00:00Z", 1800), "publish_at": "2999-01-01T18:00:00Z"}],
    }


def list_pending_videos() -> dict:
    """Return {"pending": [...], "scheduled": [...]} for the channel's own videos (FEA-08).

    pending: private, no publishAt, oldest upload first. scheduled: private with a future publishAt.
    Reads the uploads playlist (1 quota unit per page) instead of search.list, which has its own
    100-calls-per-day cap. DCS_SIMULATE=1 returns canned data without touching the API.
    """
    if os.environ.get("DCS_SIMULATE") == "1":
        return _simulated_pending_queue()

    youtube = _build_service()
    ids = _uploads_video_ids(youtube)
    now = datetime.now(timezone.utc)
    pending, scheduled = [], []
    for i in range(0, len(ids), _VIDEOS_LIST_BATCH):
        batch = ids[i:i + _VIDEOS_LIST_BATCH]
        response = youtube.videos().list(part="snippet,status,contentDetails", id=",".join(batch)).execute()
        for item in response.get("items", []):
            status = item.get("status", {})
            if status.get("privacyStatus") != "private":
                continue
            snippet = item.get("snippet", {})
            duration = _iso_duration_to_seconds(item.get("contentDetails", {}).get("duration", ""))
            thumbs = snippet.get("thumbnails", {})
            entry = {
                "video_id": item["id"],
                "title": snippet.get("title", ""),
                "uploaded_at": snippet.get("publishedAt", ""),
                "duration_sec": duration,
                "thumbnail_url": (thumbs.get("medium") or thumbs.get("default") or {}).get("url", ""),
                "is_short": duration <= SHORT_MAX_SECONDS,
            }
            publish_at = status.get("publishAt")
            if not publish_at:
                pending.append(entry)
            elif datetime.fromisoformat(publish_at.replace("Z", "+00:00")) > now:
                scheduled.append({**entry, "publish_at": publish_at})
    pending.sort(key=lambda v: v["uploaded_at"])
    scheduled.sort(key=lambda v: v["publish_at"])
    return {"pending": pending, "scheduled": scheduled}


# videos.update borra las propiedades de `status` que no se envían, salvo estas dos (documentado por YouTube)
_RESENT_STATUS_FIELDS = ("embeddable", "license", "publicStatsViewable")


def schedule_video(video_id: str, publish_at: str) -> dict:
    """Set publishAt on an existing private video, keeping its other status fields (FEA-08).

    publish_at is ISO 8601 UTC. YouTube only accepts publishAt on a private video that has never
    been published, and a past date publishes it immediately: callers must validate the date.
    Raises LookupError if the video does not exist. DCS_SIMULATE=1 skips the API.
    """
    if os.environ.get("DCS_SIMULATE") == "1":
        return {"status": "simulated", "video_id": video_id, "publish_at": publish_at}

    youtube = _build_service()
    items = youtube.videos().list(part="status", id=video_id).execute().get("items", [])
    if not items:
        raise LookupError(f"Video not found: {video_id}")
    current = items[0].get("status", {})
    status = {"privacyStatus": "private", "publishAt": publish_at}
    status.update({k: current[k] for k in _RESENT_STATUS_FIELDS if k in current})
    youtube.videos().update(part="status", body={"id": video_id, "status": status}).execute()
    return {"status": "scheduled", "video_id": video_id, "publish_at": publish_at}


def _build_description_with_chapters(description: str, chapters: list) -> str:
    """Append chapter timestamps to description if chapters are present and not already embedded."""
    if not chapters:
        return description
    if "🕐" in description or "CHAPTERS" in description or "CAPÍTULOS" in description:
        return description
    return description + "\n\n" + "\n".join(
        f"{ch['time']} {ch['label']}" for ch in chapters
    )


def _sanitize_tags(tags: list) -> list:
    """Normalise, deduplicate, and trim tags to fit YouTube's 500-character total limit."""
    import re
    import unicodedata

    clean = []
    for tag in tags:
        parts = str(tag).split(",")
        for part in parts:
            part = part.strip()
            # Strip wrapping quotes that Gemini sometimes adds: 'tag' or "tag"
            part = part.strip("'\"").strip()
            if not part:
                continue
            # Normalize unicode (fancy quotes, dashes, etc → ASCII equivalents)
            part = unicodedata.normalize("NFKD", part)
            # Strip non-ASCII entirely
            part = part.encode("ascii", "ignore").decode("ascii")
            # Keep only safe chars: letters, digits, spaces, hyphens, apostrophes, dots
            part = re.sub(r"[^\w\s\-'.]", "", part).strip()
            part = part[:30].strip()
            if part:
                clean.append(part)

    seen = set()
    deduped = []
    for t in clean:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    result = []
    total = 0
    for t in deduped:
        cost = len(t) + (1 if result else 0)
        if total + cost > 500:
            break
        result.append(t)
        total += cost

    return result


def _upload_thumbnail(youtube, video_id: str, thumbnail_path: str) -> None:
    """Set a custom thumbnail for an uploaded video via thumbnails.set."""
    import mimetypes

    from googleapiclient.http import MediaFileUpload
    mime = mimetypes.guess_type(thumbnail_path)[0] or "image/jpeg"
    media = MediaFileUpload(thumbnail_path, mimetype=mime, resumable=False)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()


def _do_insert(youtube, body: dict, video_path: str, progress_callback=None) -> dict:
    """Execute a resumable video insert and return the completed API response.

    If progress_callback is provided it is called with an int 0-100 each time the
    percentage changes during the chunked upload.
    """
    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(video_path, mimetype="video/*", resumable=True, chunksize=10 * 1024 * 1024)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    last_pct = -1
    file_size = getattr(media, "_size", None) or os.path.getsize(video_path)
    while response is None:
        _, response = req.next_chunk()
        if progress_callback is not None and file_size:
            uploaded = getattr(media, "resumable_progress", 0) or 0
            pct = int(uploaded / file_size * 100)
            if pct != last_pct:
                progress_callback(pct)
                last_pct = pct
    return response


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    chapters: list | None = None,
    privacy: str = "private",
    playlist_ids: list | None = None,
    language: str = "en",
    thumbnail_path: str | None = None,
    publish_at: str | None = None,
    progress_callback=None,
) -> dict:
    """Upload a video to YouTube with metadata; optionally assign playlists and set a thumbnail.

    Pass publish_at as an ISO 8601 datetime string (e.g. '2026-06-01T19:00:00Z') to schedule
    future publication. progress_callback, if provided, is called with an int 0-100 after each chunk.

    DCS_SIMULATE=1 skips OAuth and the API call, returning a canned result (FEA-04): lets
    agents/QA validate the full UI flow without real YouTube credentials.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if os.environ.get("DCS_SIMULATE") == "1":
        video_id = "SIMULATED-0000"
        return {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "status": "simulated",
            "privacy": "private" if publish_at else privacy,
            "publish_at": publish_at,
            "tags_skipped": False,
            "playlists_added": [],
        }

    sanitized_tags = _sanitize_tags(tags)
    lang = language if language in ("es", "en") else "en"

    youtube = _build_service()

    effective_privacy = "private" if publish_at else privacy

    body = {
        "snippet": {
            "title": title[:100],
            "description": _build_description_with_chapters(description, chapters or []),
            "tags": sanitized_tags,
            "categoryId": "20",
            "defaultLanguage": lang,
            "defaultAudioLanguage": lang
        },
        "status": {
            "privacyStatus": effective_privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    if publish_at:
        body["status"]["publishAt"] = publish_at

    tags_skipped = False
    try:
        response = _do_insert(youtube, body, video_path, progress_callback=progress_callback)
    except Exception as e:
        if "invalidTags" not in str(e):
            raise
        # Tags rejected by Google — unverified apps cannot set tags via the API.
        # This is a permanent limit for apps in OAuth Testing mode, not a scope issue.
        print("  ⚠ Tags rejected by Google (unverified app limit) — retrying without tags...")
        body["snippet"]["tags"] = []
        response = _do_insert(youtube, body, video_path, progress_callback=progress_callback)
        print("  ✓ Tags rejected by Google (unverified app limit) — uploaded without tags.")
        tags_skipped = True

    video_id = response["id"]
    result = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "status": "uploaded",
        "privacy": effective_privacy,
        "publish_at": publish_at,
        "tags_skipped": tags_skipped,
        "playlists_added": []
    }

    for pid in (playlist_ids or []):
        if not pid:
            continue
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={"snippet": {
                    "playlistId": pid,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id}
                }}
            ).execute()
            result["playlists_added"].append(pid)
            print(f"  ✓ Added to playlist: {pid}")
        except Exception as e:  # noqa: BLE001 — superficie de googleapiclient no verificable sin credenciales reales; fallo no fatal por diseño
            print(f"  ⚠ Could not add to playlist {pid}: {e}")
            result.setdefault("playlist_warnings", []).append(str(e))

    # Upload thumbnail if provided — failure is non-fatal
    if thumbnail_path:
        try:
            _upload_thumbnail(youtube, video_id, thumbnail_path)
            result["thumbnail_set"] = True
            print(f"  ✓ Thumbnail set: {thumbnail_path}")
        except Exception as e:  # noqa: BLE001 — superficie de googleapiclient no verificable sin credenciales reales; fallo no fatal por diseño
            result["thumbnail_set"] = False
            result["thumbnail_warning"] = str(e)
            print(f"  ⚠ Could not set thumbnail: {e}")

    return result


# ── Analytics ──────────────────────────────────────────────────────────────────

def build_analytics_service():
    """Build and return an authenticated YouTube Analytics API v2 service client."""
    from googleapiclient.discovery import build
    return build("youtubeAnalytics", "v2", credentials=_get_credentials())


def fetch_video_analytics(video_id: str) -> dict:
    """Fetch views, watch minutes, and likes for video_id from the YouTube Analytics API.

    Returns a dict with keys views, watch_minutes, likes, fetched_at, or {} on error.
    """
    from datetime import timedelta
    try:
        svc = build_analytics_service()
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=2)
        response = svc.reports().query(
            ids="channel==MINE",
            dimensions="video",
            filters=f"video=={video_id}",
            metrics="views,estimatedMinutesWatched,likes",
            startDate=str(today),
            endDate=str(end)
        ).execute()
        rows = response.get("rows", [])
        row = rows[0] if rows else None
        return {
            "views": int(row[1]) if row else 0,
            "watch_minutes": int(row[2]) if row else 0,
            "likes": int(row[3]) if row else 0,
            "fetched_at": datetime.now(timezone.utc).isoformat()
        }
    except Exception as e:  # noqa: BLE001 — superficie de googleapiclient no verificable sin credenciales reales; fallo no fatal por diseño
        print(f"  ⚠ Analytics fetch failed for {video_id}: {e}")
        return {}


def schedule_analytics_polling(video_id: str, filename: str) -> None:
    """Start daemon threads that poll YouTube Analytics at 1h, 6h, 12h, and 24h after upload.

    Each poll result is appended to the 'analytics' list of the matching history.json entry.
    Uses dcs_meta._memory_lock for thread-safe writes.
    """
    import dcs_meta

    POLL_OFFSETS = [3600, 21600, 43200, 86400]

    def _make_poll(delay: int):
        def _run():
            data = fetch_video_analytics(video_id)
            if data:
                with dcs_meta._memory_lock:
                    memory = dcs_meta.load_memory()
                    for entry in reversed(memory["videos"]):
                        if entry.get("video_id") == video_id or entry.get("filename") == filename:
                            entry.setdefault("analytics", []).append(data)
                            break
                    dcs_meta.save_memory(memory)
        t = threading.Timer(delay, _run)
        t.daemon = True
        t.start()

    for offset in POLL_OFFSETS:
        _make_poll(offset)
