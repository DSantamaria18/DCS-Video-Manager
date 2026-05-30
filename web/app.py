#!/usr/bin/env python3
"""
DCS YouTube Automation — Web UI
Run: python web/app.py
Then open: http://localhost:5000
"""

import os
import sys
import json
import uuid
import subprocess
import threading
import webbrowser
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

# Add parent dir to path so we can import dcs_meta
sys.path.insert(0, str(Path(__file__).parent.parent))
import dcs_meta

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB max upload

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# ── State (in-memory, per session) ──────────────────────────────────────────
processing_status = {}   # job_id -> {status, progress, message, result}
_MAX_STATUS_ENTRIES = 50


def _evict_old_jobs() -> None:
    """Keep processing_status bounded; drop oldest entries beyond the cap."""
    if len(processing_status) > _MAX_STATUS_ENTRIES:
        for key in list(processing_status.keys())[:-_MAX_STATUS_ENTRIES]:
            del processing_status[key]


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


def _open_file_dialog(initial_dir: str,
                      win_filter: str = "Video files|*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v|All files|*.*",
                      mac_types: str = "mp4, mkv, mov, avi, webm, m4v",
                      linux_filter: str = "Video files (mp4 mkv mov avi)|*.mp4 *.mkv *.mov *.avi",
                      title: str = "Select DCS video") -> str | None:
    """Open a native OS file-picker dialog and return the selected path, or None if cancelled."""
    if sys.platform == "win32":
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$f = New-Object System.Windows.Forms.OpenFileDialog;"
            f"$f.InitialDirectory = '{initial_dir}';"
            f"$f.Filter = '{win_filter}';"
            f"$f.Title = '{title}';"
            "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.FileName }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True
        )
        return result.stdout.strip() or None

    elif sys.platform == "darwin":
        script = (
            'tell application "Finder"\n'
            f'set f to choose file with prompt "{title}" '
            f'of type {{"{mac_types}"}}\n'
            'POSIX path of f\nend tell'
        )
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        return result.stdout.strip() or None

    else:
        # Linux: try zenity
        try:
            result = subprocess.run(
                ["zenity", "--file-selection",
                 f"--title={title}",
                 f"--file-filter={linux_filter}",
                 f"--filename={initial_dir}/"],
                capture_output=True, text=True
            )
            return result.stdout.strip() or None
        except FileNotFoundError:
            raise RuntimeError("File picker not available on this Linux — paste path manually.")


@app.route("/api/browse")
def browse_file():
    """Open native OS file picker and return the selected path."""
    last_folder_path = Path(__file__).parent.parent / "config" / "last_folder.txt"
    initial_dir = last_folder_path.read_text().strip() if last_folder_path.exists() else ""

    try:
        selected = _open_file_dialog(initial_dir)
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    if not selected:
        return jsonify({"cancelled": True})

    last_folder_path.parent.mkdir(exist_ok=True)
    last_folder_path.write_text(str(Path(selected).parent))

    return jsonify({"path": selected, "name": Path(selected).name})


@app.route("/api/browse_acmi")
def browse_acmi_file():
    """Open native OS file picker filtered for .acmi files and return the selected path."""
    last_folder_path = Path(__file__).parent.parent / "config" / "last_folder.txt"
    initial_dir = last_folder_path.read_text().strip() if last_folder_path.exists() else ""

    try:
        selected = _open_file_dialog(
            initial_dir,
            win_filter="TacView ACMI|*.acmi|All files|*.*",
            mac_types="acmi",
            linux_filter="TacView ACMI (acmi)|*.acmi",
            title="Select TacView ACMI file",
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400

    if not selected:
        return jsonify({"cancelled": True})

    return jsonify({"path": selected, "name": Path(selected).name})


@app.route("/api/parse_acmi", methods=["POST"])
def parse_acmi():
    """POST /api/parse_acmi — parse a TacView ACMI file and return extracted tactical events."""
    data = request.get_json()
    acmi_path = data.get("acmi_path", "").strip()

    if not acmi_path:
        return jsonify({"error": "Missing acmi_path"}), 400

    path = Path(acmi_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {acmi_path}"}), 404
    if path.suffix.lower() != ".acmi":
        return jsonify({"error": "File must be a .acmi file"}), 400

    events = dcs_meta.parse_acmi_events(path)
    if events is None:
        return jsonify({"error": "Could not parse ACMI file"}), 500

    return jsonify({
        "events": events,
        "kills": len(events.get("kills", [])),
        "sam_launches": len(events.get("sam_launches", [])),
        "bvr_launches": len(events.get("bvr_launches", [])),
        "events_text": events.get("events_text", ""),
    })


VALID_MODELS = {"gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-flash", "gemini-1.5-pro"}
_CONFIG_ALLOWED_KEYS = {"channel_name", "channel_description", "squadron",
                        "default_links", "frames_to_extract", "model",
                        "description_templates", "recordings_folder", "discord_webhook_url"}


@app.route("/api/config")
def get_config():
    """GET /api/config — return the current config.json as JSON."""
    cfg = dcs_meta.load_config()
    return jsonify(cfg)


@app.route("/api/config", methods=["POST"])
def save_config():
    """POST /api/config — validate and merge fields into config.json; description_templates uses merge semantics."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    if "frames_to_extract" in data:
        try:
            n = int(data["frames_to_extract"])
            if not (1 <= n <= 20):
                raise ValueError
            data["frames_to_extract"] = n
        except (ValueError, TypeError):
            return jsonify({"error": "frames_to_extract must be an integer between 1 and 20"}), 400

    if "model" in data and data["model"] not in VALID_MODELS:
        return jsonify({"error": f"Invalid model. Allowed: {', '.join(sorted(VALID_MODELS))}"}), 400

    existing = dcs_meta.load_config()

    # description_templates uses merge semantics so individual keys can be saved
    # without overwriting unrelated templates.
    if "description_templates" in data:
        incoming = data.pop("description_templates")
        if not isinstance(incoming, dict):
            return jsonify({"error": "description_templates must be an object"}), 400
        merged = dict(existing.get("description_templates", {}))
        for k, v in incoming.items():
            if k not in dcs_meta.VALID_TEMPLATE_KEYS:
                return jsonify({"error": f"Invalid template key: {k}"}), 400
            merged[k] = v  # empty string is valid — means "reset to default"
        existing["description_templates"] = merged

    for key in _CONFIG_ALLOWED_KEYS - {"description_templates"}:
        if key in data:
            existing[key] = data[key]

    dcs_meta.CONFIG_PATH.parent.mkdir(exist_ok=True)
    with open(dcs_meta.CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    return jsonify(existing)


@app.route("/api/description_templates")
def get_description_templates():
    """Return all 6 effective description templates (custom override or hardcoded default)."""
    cfg = dcs_meta.load_config()
    templates = {}
    custom = cfg.get("description_templates", {})
    for is_sq, lang in [(False, "en"), (True, "es")]:
        for cat in ("short", "medium", "long"):
            key = f"{lang}_{cat}"
            templates[key] = dcs_meta._build_description_rules(is_sq, cat, cfg)
    return jsonify({
        "templates": templates,
        "customised": [k for k, v in custom.items() if v],
    })


@app.route("/api/history")
def get_history():
    """GET /api/history — return the last 20 analysed videos from history.json."""
    mem = dcs_meta.load_memory()
    return jsonify(mem["videos"][-20:])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Start async analysis job."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    context = data.get("context", "").strip()
    acmi_path_str = data.get("acmi_path", "").strip()

    if not video_path:
        return jsonify({"error": "No video path provided"}), 400

    path = Path(video_path).resolve()
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    acmi_path = Path(acmi_path_str) if acmi_path_str else None
    if acmi_path and not acmi_path.exists():
        return jsonify({"error": f"ACMI file not found: {acmi_path_str}"}), 404

    if not os.environ.get("GEMINI_API_KEY"):
        return jsonify({"error": "GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/app/apikey"}), 500

    _evict_old_jobs()
    job_id = str(uuid.uuid4())[:8]
    processing_status[job_id] = {
        "status": "running",
        "progress": 0,
        "message": "Starting analysis...",
        "result": None,
        "error": None
    }

    def run_analysis():
        try:
            processing_status[job_id]["message"] = "Extracting video frames..."
            processing_status[job_id]["progress"] = 20

            cfg = dcs_meta.load_config()
            mem = dcs_meta.load_memory()

            frames = dcs_meta.extract_frames(path, cfg["frames_to_extract"])
            if not frames:
                processing_status[job_id]["status"] = "error"
                processing_status[job_id]["error"] = "Could not extract frames. Is ffmpeg installed?"
                return

            processing_status[job_id]["message"] = f"Extracted {len(frames)} frames. Calling Gemini..."
            processing_status[job_id]["progress"] = 50

            gemini_error = None
            try:
                metadata = dcs_meta.generate_metadata(path, context, cfg, mem, frames=frames,
                                                       acmi_path=acmi_path)
            except Exception as e:
                gemini_error = str(e)
                metadata = None

            if not metadata:
                metadata = dcs_meta.build_fallback_metadata(path, context, cfg)
                processing_status[job_id]["fallback_warning"] = (
                    "Analysis failed — using fallback metadata. Edit before upload."
                )
                if gemini_error:
                    processing_status[job_id]["gemini_error"] = gemini_error

            processing_status[job_id]["message"] = "Saving output files..."
            processing_status[job_id]["progress"] = 80

            txt_path, json_path = dcs_meta.save_output(metadata, path, cfg)
            dcs_meta.update_memory(metadata, path)

            processing_status[job_id]["status"] = "done"
            processing_status[job_id]["progress"] = 100
            processing_status[job_id]["message"] = "Done!"
            processing_status[job_id]["result"] = {
                "metadata": metadata,
                "txt_path": str(txt_path),
                "json_path": str(json_path),
                "video_name": path.name,
                "fallback_warning": processing_status[job_id].get("fallback_warning"),
            }

        except Exception as e:
            processing_status[job_id]["status"] = "error"
            processing_status[job_id]["error"] = str(e)

    thread = threading.Thread(target=run_analysis, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/thumbnail", methods=["POST"])
def generate_thumbnail():
    """POST /api/thumbnail — extract and score candidate thumbnails, return their serve paths."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    metadata = data.get("metadata", {})

    if not video_path or not metadata:
        return jsonify({"error": "Missing video_path or metadata"}), 400

    path = Path(video_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    cfg = dcs_meta.load_config()
    try:
        thumb_paths = dcs_meta.generate_thumbnail_on_demand(metadata, path, cfg)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify({"thumbnails": [f"/output/{p.name}" for p in thumb_paths]})


@app.route("/output/<path:filename>")
def serve_output_file(filename):
    """GET /output/<filename> — serve a generated file (thumbnail, JSON, TXT) from the output folder."""
    return send_from_directory(str(OUTPUT_DIR), filename)


@app.route("/api/status/<job_id>")
def job_status(job_id):
    """GET /api/status/<job_id> — return the current status and result of an analysis job."""
    if job_id not in processing_status:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(processing_status[job_id])


def _post_discord_webhook(webhook_url: str, title: str, youtube_url: str,
                           description: str, thumbnail_url: str = "") -> None:
    """POST an embed to a Discord webhook. Non-fatal: logs and returns on failure."""
    import urllib.request as _req
    import urllib.error as _err

    embed = {
        "title": title,
        "url": youtube_url,
        "description": description[:200],
        "color": 3447003,
    }
    if thumbnail_url:
        embed["thumbnail"] = {"url": thumbnail_url}

    payload = json.dumps({"embeds": [embed]}).encode("utf-8")
    request_obj = _req.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _req.urlopen(request_obj, timeout=10):
            pass
        print(f"  ✓ Discord webhook posted")
    except (_err.HTTPError, _err.URLError, OSError) as e:
        print(f"  ⚠ Discord webhook failed (non-fatal): {e}")


@app.route("/api/upload_youtube", methods=["POST"])
def upload_youtube():
    """Upload video to YouTube with generated metadata."""
    data = request.get_json()
    video_path = str(Path(data.get("video_path", "").strip()).resolve())
    metadata = data.get("metadata", {})
    playlist_ids = data.get("playlist_ids", [])  # list of playlist IDs
    thumbnail_url = data.get("thumbnail_url", "").strip()
    publish_at = data.get("publish_at", "").strip() or None  # ISO 8601 string, optional

    if not video_path or not metadata:
        return jsonify({"error": "Missing video_path or metadata"}), 400

    # Resolve the thumbnail URL (/output/filename.jpg) to a local filesystem path
    thumbnail_path = None
    if thumbnail_url.startswith("/output/"):
        candidate = OUTPUT_DIR / Path(thumbnail_url).name
        if candidate.exists():
            thumbnail_path = str(candidate)

    try:
        from youtube_uploader import upload_video
        result = upload_video(
            video_path=video_path,
            title=metadata.get("title", ""),
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            chapters=metadata.get("chapters", []),
            privacy="private",
            playlist_ids=playlist_ids,
            language=metadata.get("language", "en"),
            thumbnail_path=thumbnail_path,
            publish_at=publish_at,
        )
        video_id = result.get("video_id")
        if video_id:
            dcs_meta.update_memory_video_id(Path(video_path).name, video_id)

        # Post Discord webhook notification if configured — non-fatal
        cfg = dcs_meta.load_config()
        webhook_url = cfg.get("discord_webhook_url", "").strip()
        if webhook_url and video_id:
            yt_url = f"https://www.youtube.com/watch?v={video_id}"
            _post_discord_webhook(
                webhook_url,
                title=metadata.get("title", ""),
                youtube_url=yt_url,
                description=metadata.get("description", ""),
            )

        return jsonify(result)
    except ImportError:
        return jsonify({"error": "youtube_uploader module not found"}), 500
    except Exception as e:
        import traceback
        full_error = traceback.format_exc()
        print(f"\n=== UPLOAD ERROR ===\n{full_error}\n===================")
        return jsonify({"error": str(e), "traceback": full_error}), 500


@app.route("/api/youtube/auth_url")
def youtube_auth_url():
    """GET /api/youtube/auth_url — start the OAuth flow; browser opens automatically."""
    try:
        from youtube_uploader import get_auth_url
        url = get_auth_url()
        return jsonify({"url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube/wait_auth")
def youtube_wait_auth():
    """Long-poll: waits until Google redirects back with the token."""
    try:
        from youtube_uploader import wait_for_auth
        result = wait_for_auth()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube/revoke", methods=["POST"])
def youtube_revoke():
    """Delete saved token to force re-authorization."""
    token_path = Path(__file__).parent.parent / "config" / "youtube_token.json"
    if token_path.exists():
        token_path.unlink()
    return jsonify({"ok": True})


@app.route("/api/youtube/status")
def youtube_auth_status():
    """GET /api/youtube/status — return whether a valid YouTube token file exists."""
    token_path = Path(__file__).parent.parent / "config" / "youtube_token.json"
    return jsonify({"authenticated": token_path.exists()})


@app.route("/api/seo_check", methods=["POST"])
def seo_check():
    """POST /api/seo_check — validate description SEO; returns {issues: [...]}."""
    data = request.get_json()
    cfg = dcs_meta.load_config()
    issues = dcs_meta.check_description_seo(
        description=data.get("description", ""),
        title=data.get("title", ""),
        tags=data.get("tags", []),
        aircraft=data.get("aircraft", ""),
        mission_type=data.get("mission_type", ""),
        chapters=data.get("chapters", []),
        config=cfg,
    )
    return jsonify({"issues": issues})


@app.route("/api/seo_rewrite", methods=["POST"])
def seo_rewrite():
    """POST /api/seo_rewrite — rewrite description via Gemini to fix SEO issues; returns {description}."""
    data = request.get_json()
    cfg = dcs_meta.load_config()
    try:
        new_desc = dcs_meta.rewrite_description_seo(
            description=data.get("description", ""),
            issues=data.get("issues", []),
            aircraft=data.get("aircraft", ""),
            mission_type=data.get("mission_type", ""),
            language=data.get("language", "en"),
            config=cfg,
        )
        return jsonify({"description": new_desc})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/debrief", methods=["POST"])
def debrief():
    """POST /api/debrief — generate a mission debrief report via Gemini; returns {report: str}."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    metadata = data.get("metadata", {})
    acmi_events = data.get("acmi_events") or None

    if not video_path or not metadata:
        return jsonify({"error": "Missing video_path or metadata"}), 400

    path = Path(video_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    cfg = dcs_meta.load_config()
    try:
        report = dcs_meta.generate_debrief(metadata, path, cfg, acmi_events=acmi_events)
        return jsonify({"report": report})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Aircraft alias map: canonical fragments → list of alias tokens to match against playlist titles
_AIRCRAFT_ALIASES: dict[str, list[str]] = {
    "f/a-18":  ["fa18", "fa-18", "hornet", "f18", "f-18"],
    "f-18":    ["fa18", "fa-18", "hornet", "f18", "f-18"],
    "hornet":  ["fa18", "fa-18", "hornet", "f18", "f-18"],
    "f-16":    ["f16", "viper", "f-16c", "f16c"],
    "viper":   ["f16", "viper", "f-16c", "f16c"],
    "f-14":    ["f14", "tomcat", "f-14b", "f14b", "phoenix"],
    "tomcat":  ["f14", "tomcat", "f-14b", "f14b"],
    "uh-1":    ["uh1h", "uh-1h", "huey", "helicopter"],
    "huey":    ["uh1h", "uh-1h", "huey"],
    "a-10":    ["a10c", "a-10c", "warthog", "thunderbolt"],
    "warthog": ["a10c", "a-10c", "warthog"],
    "c-130":   ["c130j", "c-130j", "hercules"],
    "hercules":["c130j", "c-130j", "hercules"],
    "ah-64":   ["ah64d", "ah-64d", "apache", "longbow"],
    "apache":  ["ah64d", "ah-64d", "apache"],
}


def _suggest_playlist_ids(metadata: dict, playlists: list[dict]) -> list[str]:
    """Return playlist IDs whose title matches terms from aircraft/mission_type/campaign.

    Tokenises each metadata field into lowercase words (≥2 chars, letters/digits only),
    then expands aircraft tokens through _AIRCRAFT_ALIASES so common aircraft names
    (e.g. 'F/A-18C' → 'hornet', 'fa18', 'fa-18') match playlist titles like 'Hornet Pilot'.
    """
    import re as _re
    fields = [
        metadata.get("aircraft", ""),
        metadata.get("mission_type", ""),
        metadata.get("campaign", ""),
    ]
    terms: set[str] = set()
    for field in fields:
        for tok in _re.split(r"[^a-z0-9]+", field.lower()):
            if len(tok) >= 2:
                terms.add(tok)
                # Expand via alias map: check if any alias key is a substring of the token or vice versa
                for alias_key, alias_list in _AIRCRAFT_ALIASES.items():
                    if alias_key in field.lower():
                        terms.update(alias_list)

    # Also directly expand the raw aircraft string against alias keys
    aircraft_raw = metadata.get("aircraft", "").lower()
    for alias_key, alias_list in _AIRCRAFT_ALIASES.items():
        if alias_key in aircraft_raw:
            terms.update(alias_list)

    if not terms:
        return []

    matched = []
    for pl in playlists:
        title_lower = pl.get("title", "").lower()
        if any(term in title_lower for term in terms):
            matched.append(pl["id"])
    return matched


@app.route("/api/suggest_playlists", methods=["POST"])
def suggest_playlists():
    """Given metadata and a playlist list, return IDs of playlists that match."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400
    metadata = data.get("metadata", {})
    playlists = data.get("playlists", [])
    return jsonify({"suggested": _suggest_playlist_ids(metadata, playlists)})


@app.route("/api/playlists")
def get_playlists():
    """GET /api/playlists — fetch the authenticated channel's playlists from YouTube."""
    try:
        from youtube_uploader import get_playlists
        playlists = get_playlists()
        return jsonify(playlists)
    except Exception as e:
        return jsonify({"error": str(e), "playlists": []}), 200


# ── Batch watcher endpoints ───────────────────────────────────────────────────

@app.route("/api/batch/start", methods=["POST"])
def batch_start():
    """POST /api/batch/start — start the folder watcher for automatic .mkv queuing."""
    import batch_watcher

    cfg = dcs_meta.load_config()
    folder = cfg.get("recordings_folder", "").strip()
    if not folder:
        return jsonify({"error": "recordings_folder not configured. Set it in Setup."}), 400

    if batch_watcher.is_running():
        return jsonify({"ok": True, "message": "Watcher already running"})

    def _enqueue(file_path: str):
        """Queue a new .mkv file discovered by the folder watcher."""
        _evict_old_jobs()
        job_id = str(uuid.uuid4())[:8]
        processing_status[job_id] = {
            "status": "queued",
            "progress": 0,
            "message": f"Queued: {Path(file_path).name}",
            "result": None,
            "error": None,
            "video_path": file_path,
            "batch": True,
        }

    try:
        batch_watcher.start_watcher(folder, _enqueue)
        return jsonify({"ok": True, "folder": folder})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/batch/stop", methods=["POST"])
def batch_stop():
    """POST /api/batch/stop — stop the folder watcher."""
    import batch_watcher
    batch_watcher.stop_watcher()
    return jsonify({"ok": True})


@app.route("/api/batch/status")
def batch_status():
    """GET /api/batch/status — return all queued/running batch jobs."""
    import batch_watcher
    batch_jobs = {
        jid: info for jid, info in processing_status.items()
        if info.get("batch")
    }
    return jsonify({
        "running": batch_watcher.is_running(),
        "jobs": batch_jobs,
    })


@app.route("/api/export_history_csv")
def export_history_csv():
    """GET /api/export_history_csv — return history.json as a downloadable CSV file."""
    from flask import Response
    import csv
    import io

    mem = dcs_meta.load_memory()
    videos = mem.get("videos", [])

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["date", "filename", "aircraft", "map", "mission_type", "title", "video_id"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for v in videos:
        writer.writerow({
            "date": v.get("date", ""),
            "filename": v.get("filename", ""),
            "aircraft": v.get("aircraft", ""),
            "map": v.get("map", ""),
            "mission_type": v.get("mission_type", ""),
            "title": v.get("title", ""),
            "video_id": v.get("video_id", ""),
        })

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=dcs_history.csv"},
    )


# ── Narration script ──────────────────────────────────────────────────────────

@app.route("/api/narration", methods=["POST"])
def narration():
    """POST /api/narration — generate a voiceover narration script via Gemini."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    metadata = data.get("metadata", {})

    if not video_path or not metadata:
        return jsonify({"error": "Missing video_path or metadata"}), 400

    path = Path(video_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    cfg = dcs_meta.load_config()
    try:
        script = dcs_meta.generate_narration_script(metadata, path, cfg)
        return jsonify({"script": script})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Duplicate check ───────────────────────────────────────────────────────────

@app.route("/api/check_duplicate", methods=["POST"])
def check_duplicate_endpoint():
    """POST /api/check_duplicate — check if the analysed video is a duplicate of a history entry."""
    data = request.get_json()
    metadata = data.get("metadata", {})
    if not metadata:
        return jsonify({"error": "Missing metadata"}), 400
    mem = dcs_meta.load_memory()
    result = dcs_meta.check_duplicate(metadata, mem)
    return jsonify(result)


# ── OBS metadata extraction ───────────────────────────────────────────────────

@app.route("/api/obs_metadata", methods=["POST"])
def obs_metadata():
    """POST /api/obs_metadata — extract OBS scene metadata from MKV file tags."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    if not video_path:
        return jsonify({"error": "Missing video_path"}), 400

    path = Path(video_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    try:
        obs_data = dcs_meta.extract_obs_metadata(path)
        return jsonify(obs_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Social media captions ─────────────────────────────────────────────────────

@app.route("/api/social_captions", methods=["POST"])
def social_captions():
    """POST /api/social_captions — generate platform-adapted social captions from metadata."""
    data = request.get_json()
    metadata = data.get("metadata", {})
    if not metadata:
        return jsonify({"error": "Missing metadata"}), 400
    cfg = dcs_meta.load_config()
    try:
        captions = dcs_meta.generate_social_captions(metadata, cfg)
        return jsonify(captions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Pre-upload checklist ──────────────────────────────────────────────────────

@app.route("/api/upload_checklist", methods=["POST"])
def upload_checklist():
    """POST /api/upload_checklist — run pre-upload metadata validation; returns checklist items."""
    data = request.get_json()
    metadata = data.get("metadata", {})
    if not metadata:
        return jsonify({"error": "Missing metadata"}), 400
    cfg = dcs_meta.load_config()
    checks = dcs_meta.run_upload_checklist(metadata, cfg)
    return jsonify({"checklist": checks})


# ── Competitor analysis ───────────────────────────────────────────────────────

@app.route("/api/competitors")
def competitors():
    """GET /api/competitors?aircraft=<aircraft>&mission_type=<mission_type> — search YouTube for similar videos."""
    aircraft = request.args.get("aircraft", "").strip()
    mission_type = request.args.get("mission_type", "").strip()

    if not aircraft and not mission_type:
        return jsonify({"error": "Provide aircraft or mission_type query parameter"}), 400

    query = f"DCS World {aircraft} {mission_type}".strip()

    try:
        from youtube_uploader import _build_service
        youtube = _build_service()
        from datetime import datetime, timedelta, timezone
        published_after = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        resp = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            maxResults=5,
            publishedAfter=published_after,
            order="viewCount",
        ).execute()
        results = []
        for item in resp.get("items", []):
            snippet = item.get("snippet", {})
            results.append({
                "title": snippet.get("title", ""),
                "channel": snippet.get("channelTitle", ""),
                "published": snippet.get("publishedAt", ""),
                "video_id": item.get("id", {}).get("videoId", ""),
            })
        return jsonify({"results": results, "query": query})
    except Exception as e:
        return jsonify({"results": [], "error": str(e), "query": query})


# ── Channel stats ─────────────────────────────────────────────────────────────

@app.route("/api/stats")
def get_stats():
    """GET /api/stats — return aggregated channel history for the Stats dashboard tab."""
    from collections import Counter

    mem = dcs_meta.load_memory()
    videos = mem.get("videos", [])

    module_counts = Counter(v.get("aircraft", "Unknown") for v in videos if v.get("aircraft"))
    map_counts = Counter(v.get("map", "Unknown") for v in videos if v.get("map"))
    mission_counts = Counter(v.get("mission_type", "Unknown") for v in videos if v.get("mission_type"))

    uploads_by_month: dict = {}
    for v in videos:
        date = v.get("date", "")
        if date and len(date) >= 7:
            month = date[:7]
            uploads_by_month[month] = uploads_by_month.get(month, 0) + 1

    top_by_views = [
        {"title": v.get("title", ""), "video_id": v.get("video_id", "")}
        for v in videos
        if v.get("video_id")
    ][:5]

    return jsonify({
        "total_videos": len(videos),
        "by_module": dict(module_counts.most_common(10)),
        "by_map": dict(map_counts.most_common(5)),
        "by_mission_type": dict(mission_counts.most_common(5)),
        "uploads_by_month": uploads_by_month,
        "top_videos": top_by_views,
    })


if __name__ == "__main__":
    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(1.2)
        webbrowser.open("http://localhost:5000")

    threading.Thread(target=open_browser, daemon=True).start()

    print("\n" + "═" * 50)
    print("  DCS YouTube Automation — TheCylonPilot")
    print("  http://localhost:5000")
    print("═" * 50 + "\n")
    app.run(debug=False, port=5000)
