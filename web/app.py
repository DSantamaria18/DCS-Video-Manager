#!/usr/bin/env python3
"""
DCS YouTube Automation — Web UI
Run: python web/app.py
Then open: http://localhost:5000
"""

import os
import sys
import json
import threading
import webbrowser
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

# Add parent dir to path so we can import dcs_meta
sys.path.insert(0, str(Path(__file__).parent.parent))
import dcs_meta

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB max upload

# ── State (in-memory, per session) ──────────────────────────────────────────
processing_status = {}   # job_id -> {status, progress, message, result}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/browse")
def browse_file():
    """Open native OS file picker and return the selected path."""
    import subprocess, sys

    # Remember last folder used
    last_folder_path = Path(__file__).parent.parent / "config" / "last_folder.txt"
    initial_dir = ""
    if last_folder_path.exists():
        initial_dir = last_folder_path.read_text().strip()

    selected = None

    if sys.platform == "win32":
        # PowerShell OpenFileDialog
        ps_script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            f"$f = New-Object System.Windows.Forms.OpenFileDialog;"
            f"$f.InitialDirectory = '{initial_dir}';"
            "$f.Filter = 'Video files|*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v|All files|*.*';"
            "$f.Title = 'Select DCS video';"
            "if ($f.ShowDialog() -eq 'OK') { Write-Output $f.FileName }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True
        )
        selected = result.stdout.strip() or None

    elif sys.platform == "darwin":
        # macOS osascript
        extensions = "mp4, mkv, mov, avi, webm, m4v"
        script = (
            f'tell application "Finder"\n'
            f'set f to choose file with prompt "Select DCS video" '
            f'of type {{"{extensions}"}}\n'
            f'POSIX path of f\nend tell'
        )
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        selected = result.stdout.strip() or None

    else:
        # Linux: try zenity or kdialog
        try:
            result = subprocess.run(
                ["zenity", "--file-selection",
                 "--title=Select DCS video",
                 "--file-filter=Video files (mp4 mkv mov avi)|*.mp4 *.mkv *.mov *.avi",
                 f"--filename={initial_dir}/"],
                capture_output=True, text=True
            )
            selected = result.stdout.strip() or None
        except FileNotFoundError:
            return jsonify({"error": "File picker not available on this Linux. Paste path manually."}), 400

    if not selected:
        return jsonify({"cancelled": True})

    # Save folder for next time
    folder = str(Path(selected).parent)
    last_folder_path.parent.mkdir(exist_ok=True)
    last_folder_path.write_text(folder)

    return jsonify({"path": selected, "name": Path(selected).name})


@app.route("/api/config")
def get_config():
    cfg = dcs_meta.load_config()
    return jsonify(cfg)


@app.route("/api/history")
def get_history():
    mem = dcs_meta.load_memory()
    return jsonify(mem["videos"][-20:])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Start async analysis job."""
    import uuid

    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    context = data.get("context", "").strip()

    if not video_path:
        return jsonify({"error": "No video path provided"}), 400

    path = Path(video_path)
    if not path.exists():
        return jsonify({"error": f"File not found: {video_path}"}), 404

    if not os.environ.get("GEMINI_API_KEY"):
        return jsonify({"error": "GEMINI_API_KEY not set. Get a free key at https://aistudio.google.com/app/apikey"}), 500

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

            processing_status[job_id]["message"] = f"Extracted {len(frames)} frames. Calling Claude..."
            processing_status[job_id]["progress"] = 50

            metadata = dcs_meta.generate_metadata(path, context, cfg, mem)
            if not metadata:
                processing_status[job_id]["status"] = "error"
                processing_status[job_id]["error"] = "Claude returned empty metadata. Try adding more context."
                return

            processing_status[job_id]["message"] = "Saving output files..."
            processing_status[job_id]["progress"] = 80

            txt_path, json_path = dcs_meta.save_output(metadata, path, cfg)
            dcs_meta.update_memory(metadata, path, mem)

            processing_status[job_id]["status"] = "done"
            processing_status[job_id]["progress"] = 100
            processing_status[job_id]["message"] = "Done!"
            processing_status[job_id]["result"] = {
                "metadata": metadata,
                "txt_path": str(txt_path),
                "json_path": str(json_path),
                "video_name": path.name
            }

        except Exception as e:
            processing_status[job_id]["status"] = "error"
            processing_status[job_id]["error"] = str(e)

    thread = threading.Thread(target=run_analysis, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/api/thumbnail", methods=["POST"])
def generate_thumbnail():
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
    output_dir = Path(__file__).parent.parent / "output"
    return send_from_directory(str(output_dir), filename)


@app.route("/api/status/<job_id>")
def job_status(job_id):
    if job_id not in processing_status:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(processing_status[job_id])


@app.route("/api/upload_youtube", methods=["POST"])
def upload_youtube():
    """Upload video to YouTube with generated metadata."""
    data = request.get_json()
    video_path = data.get("video_path", "").strip()
    metadata = data.get("metadata", {})
    playlist_ids = data.get("playlist_ids", [])  # list of playlist IDs
    thumbnail_url = data.get("thumbnail_url", "").strip()

    if not video_path or not metadata:
        return jsonify({"error": "Missing video_path or metadata"}), 400

    # Resolve the thumbnail URL (/output/filename.jpg) to a local filesystem path
    thumbnail_path = None
    if thumbnail_url.startswith("/output/"):
        candidate = Path(__file__).parent.parent / "output" / Path(thumbnail_url).name
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
            thumbnail_path=thumbnail_path
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
    try:
        from youtube_uploader import get_auth_url
        url = get_auth_url()
        return jsonify({"url": url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/youtube/auth_callback", methods=["POST"])
def youtube_auth_callback():
    """Legacy endpoint — kept for compatibility."""
    return jsonify({"error": "Use the new auth flow — click 'Authorize YouTube' button."}), 400


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
    from pathlib import Path
    token_path = Path(__file__).parent.parent / "config" / "youtube_token.json"
    if token_path.exists():
        token_path.unlink()
    return jsonify({"ok": True})


@app.route("/api/youtube/status")
def youtube_auth_status():
    token_path = Path(__file__).parent.parent / "config" / "youtube_token.json"
    return jsonify({"authenticated": token_path.exists()})


@app.route("/api/playlists")
def get_playlists():
    try:
        from youtube_uploader import get_playlists
        playlists = get_playlists()
        return jsonify(playlists)
    except Exception as e:
        return jsonify({"error": str(e), "playlists": []}), 200


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
