"""
YouTube uploader — TheCylonPilot DCS Automation
Uses YouTube Data API v3 with OAuth2.
Credential type: Desktop app (InstalledAppFlow)
"""

import json
import threading
from pathlib import Path

BASE               = Path(__file__).parent
CLIENT_SECRET_PATH = BASE / "config" / "client_secret.json"
TOKEN_PATH         = BASE / "config" / "youtube_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl"
]

_auth_state = {"result": None, "done": threading.Event()}


# ── Auth ──────────────────────────────────────────────────────────────────────

def get_auth_url() -> str:
    """
    Launch OAuth flow in background thread using run_local_server().
    This works with Desktop app credentials — no redirect URI config needed.
    Returns a placeholder string; the browser is opened by the thread.
    Frontend should call wait_for_auth() via /api/youtube/wait_auth.
    """
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
        except Exception as e:
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
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request

    if not TOKEN_PATH.exists():
        raise PermissionError("Not authenticated. Complete YouTube OAuth setup first.")

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    return creds


def _build_service():
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=_get_credentials())


# ── YouTube API ───────────────────────────────────────────────────────────────

def get_playlists() -> list:
    try:
        response = _build_service().playlists().list(
            part="snippet", mine=True, maxResults=50
        ).execute()
        return [
            {"id": item["id"], "title": item["snippet"]["title"]}
            for item in response.get("items", [])
        ]
    except Exception:
        return []


def _build_description_with_chapters(description: str, chapters: list) -> str:
    if not chapters:
        return description
    if "🕐" in description or "CHAPTERS" in description or "CAPÍTULOS" in description:
        return description
    return description + "\n\n" + "\n".join(
        f"{ch['time']} {ch['label']}" for ch in chapters
    )


def _sanitize_tags(tags: list) -> list:
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

    print(f"  Tags repr: {[repr(t) for t in result]}")
    return result


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    chapters: list = None,
    privacy: str = "private",
    playlist_ids: list = None
) -> dict:
    from googleapiclient.http import MediaFileUpload

    sanitized_tags = _sanitize_tags(tags)
    print(f"  Uploading: {title[:60]}")
    print(f"  Tags count: {len(sanitized_tags)}, total chars: {sum(len(t) for t in sanitized_tags)}")
    print(f"  First 3 tags raw bytes: {[t.encode() for t in sanitized_tags[:3]]}")

    # Detect language from tags to set correct defaultLanguage
    lang = "es" if any(t in sanitized_tags for t in ["escuadron111", "e111", "simulacion aerea"]) else "en"

    youtube = _build_service()
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
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False
        }
    }

    import os
    print(f"  Video path: {video_path}")
    print(f"  File exists: {os.path.exists(video_path)}")
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    media = MediaFileUpload(
        video_path, mimetype="video/*",
        resumable=True, chunksize=10 * 1024 * 1024
    )

    print(f"  Body snippet keys: {list(body['snippet'].keys())}")
    print(f"  Description length: {len(body['snippet']['description'])}")

    insert_request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )

    response = None
    try:
        while response is None:
            _, response = insert_request.next_chunk()
    except Exception as e:
        error_str = str(e)
        if "invalidTags" in error_str:
            print("  ⚠ invalidTags error — retrying without tags...")
            body["snippet"]["tags"] = []
            media2 = MediaFileUpload(
                video_path, mimetype="video/*",
                resumable=True, chunksize=10 * 1024 * 1024
            )
            insert_request2 = youtube.videos().insert(
                part="snippet,status", body=body, media_body=media2
            )
            response = None
            while response is None:
                _, response = insert_request2.next_chunk()
            print("  ✓ Uploaded without tags — add them manually in YouTube Studio")
        else:
            raise

    video_id = response["id"]
    result = {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "status": "uploaded",
        "privacy": privacy,
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
        except Exception as e:
            print(f"  ⚠ Could not add to playlist {pid}: {e}")
            result.setdefault("playlist_warnings", []).append(str(e))

    return result
