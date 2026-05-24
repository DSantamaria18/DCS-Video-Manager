#!/usr/bin/env python3
"""
DCS YouTube Metadata Generator — TheCylonPilot
Analyzes DCS World video files and generates optimized YouTube metadata.
Uses Google Gemini Vision API (gemini-1.5-flash) — free tier: 1500 req/day.
"""

import os
import sys
import json
import base64
import subprocess
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config" / "config.json"
MEMORY_PATH = Path(__file__).parent / "memory" / "history.json"
OUTPUT_PATH = Path(__file__).parent / "output"

DEFAULT_CONFIG = {
    "channel_name": "TheCylonPilot",
    "channel_description": "DCS World simulation — learning through mistakes, F/A-18C Hornet main module, also F-16C, F-14, UH-1H, A-10C.",
    "squadron": "Escuadrón 111 (E111)",
    "default_links": {
        "dcs_a10c_playlist": "https://youtube.com/playlist?list=PLbOMVlk368l6igw-XjMgNI8msORPNLAoQ",
        "dcs_huey_playlist": "https://youtube.com/playlist?list=PLbOMVlk368l4givZ9uAOA67mKLGFrbk7C",
        "dcs_f18_playlist":  "https://youtube.com/playlist?list=PLbOMVlk368l6M0sXB-Fv6I7tFBs6UBd3Y",
        "twitter":           "https://twitter.com/thecylonpilot",
        "twitch":            "https://www.twitch.tv/thecylonpilot",
        "buymeacoffee":      "https://www.buymeacoffee.com/pilotcylon",
        "escuadron111":      "https://www.escuadron111.eu/"
    },
    "frames_to_extract": 8,
    "model": "gemini-2.5-flash"
}

SQUADRON_KEYWORDS = ["escuadron", "escuadrón", "e111", "111", "squad", "multiplayer", "multi"]

# ── Config & memory ──────────────────────────────────────────────────────────

def load_config():
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return {**DEFAULT_CONFIG, **json.load(f)}
    with open(CONFIG_PATH, "w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    return DEFAULT_CONFIG


def load_memory():
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    if MEMORY_PATH.exists():
        with open(MEMORY_PATH) as f:
            return json.load(f)
    return {"videos": []}


def save_memory(memory):
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    with open(MEMORY_PATH, "w") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


def is_squadron_video(user_context: str) -> bool:
    ctx = user_context.lower()
    return any(k in ctx for k in SQUADRON_KEYWORDS)

# ── Frame extraction ─────────────────────────────────────────────────────────

def extract_frames(video_path: Path, n_frames: int = 8) -> list[str]:
    """Extract N evenly-spaced frames via ffmpeg. Returns list of base64 JPEG strings."""
    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True, text=True, check=True
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except Exception as e:
        print(f"  ⚠ Could not read video duration: {e}")
        print("  → Make sure ffmpeg/ffprobe is installed (https://ffmpeg.org)")
        return []

    frames = []
    interval = duration / (n_frames + 1)

    for i in range(1, n_frames + 1):
        timestamp = interval * i
        tmp_path = tmp_dir / f"dcs_frame_{i}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(timestamp),
                "-i", str(video_path),
                "-vframes", "1", "-q:v", "3",
                "-vf", "scale=1280:-1",
                str(tmp_path)
            ], capture_output=True, check=True)

            with open(tmp_path, "rb") as f:
                frames.append(base64.standard_b64encode(f.read()).decode("utf-8"))
            tmp_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"  ⚠ Frame {i} failed: {e}")

    print(f"  ✓ Extracted {len(frames)} frames")
    return frames

# ── Prompt ───────────────────────────────────────────────────────────────────

def build_prompt(user_context: str, config: dict, is_squadron: bool, memory: dict) -> str:
    recent = memory["videos"][-5:] if memory["videos"] else []
    memory_block = ""
    if recent:
        memory_block = "\n\nRECENT VIDEOS (for style consistency):\n"
        for v in recent:
            memory_block += f"- [{v['date']}] {v['title']} ({v['language']})\n"

    if is_squadron:
        lang_instructions = """LANGUAGE: Spanish (Spain). Formal but warm tone.
This is a squadron mission video with Escuadrón 111 (E111), a veteran Spanish virtual aviation community with 25+ years of history.
Tone: mission report style, proud of the team, mention callsigns/roles if visible in the video."""
    else:
        lang_instructions = """LANGUAGE: English. Tone: enthusiastic learner, honest about mistakes, technically interested.
This is a solo/campaign video. The pilot is learning DCS and shares both successes and failures to help other beginners."""

    return f"""You are a YouTube metadata specialist for the DCS World simulation channel "TheCylonPilot".

CHANNEL IDENTITY:
- Creator: Spanish simmer, 47 years old, IT professional
- Main module: F/A-18C Hornet | Also flies: F-16C, F-14, UH-1H, A-10C
- Philosophy: Learning through mistakes, helping beginners
- Squadron: Escuadrón 111 (E111) — veteran Spanish virtual aviation community

{lang_instructions}

USER CONTEXT FOR THIS VIDEO:
{user_context if user_context else "(none provided — infer everything from video frames)"}
{memory_block}

TASK:
Analyze the provided video frames (extracted from a DCS World gameplay recording) and generate complete YouTube metadata.

Pay close attention to:
- The cockpit/HUD to identify the aircraft module
- The terrain, map labels, or mission briefing screens to identify the DCS map
- Any text overlays, mission names, or briefing screens visible
- The type of activity shown (combat, training, refueling, landing, etc.)

OUTPUT FORMAT — respond ONLY with a valid JSON object. No markdown fences, no explanation, no preamble. Just the raw JSON:

{{
  "title": "...",
  "description": "...",
  "tags": ["tag1", "tag2", ...],
  "chapters": [
    {{"time": "0:00", "label": "..."}},
    ...
  ],
  "language": "en",
  "aircraft": "...",
  "map": "...",
  "mission_type": "...",
  "analysis_notes": "brief explanation of what you saw in the frames"
}}

TITLE RULES:
- English solo: "DCS World | [Aircraft] | [Mission/Action] | [Campaign if known]"
  Example: "DCS World | F/A-18C Hornet | Night SEAD Strike | Raven One Campaign"
- Spanish squadron: "DCS World | [Aeronave] | [Nombre Misión] | E111"
  Example: "DCS World | F/A-18C Hornet | Operación Trueno | E111"
- Max 70 characters. No clickbait. No ALL CAPS.

DESCRIPTION RULES (English solo):
[1-2 sentence engaging hook describing the mission/action]

✈ Aircraft: [full name]
🗺 Map: [map name]
🎯 Mission type: [CAS / BVR / AAR / SEAD / Strike / Training / etc.]
📋 Campaign: [if applicable]

[2-3 sentences of honest narrative: what happened, key moments, mistakes or wins]

---
🕐 CHAPTERS
[list chapters here if more than 5 min]

---
📺 MORE DCS VIDEOS
[relevant playlists]

🔗 FOLLOW
Twitter: [link]
Twitch: [link]
Support: [link]

#DCSWorld #[Aircraft] #[relevant tags]

DESCRIPTION RULES (Spanish squadron):
[Hook: 1-2 frases describiendo la misión con tono de informe]

✈ Aeronave: [nombre]
🗺 Mapa: [mapa]
🎯 Tipo de misión: [tipo]
👥 Escuadrón: Escuadrón 111 (E111) — https://www.escuadron111.eu/

[2-3 frases narrando la misión]

---
🕐 CAPÍTULOS
[si el video dura más de 5 min]

---
📺 MÁS VÍDEOS DCS
[playlists relevantes]

🔗 SÍGUENOS
Twitter: https://twitter.com/thecylonpilot
Twitch: https://www.twitch.tv/thecylonpilot

#DCSWorld #[Aeronave] #[tags relevantes]

TAGS RULES:
- 30-40 tags total
- Return tags as plain strings with NO surrounding quotes — correct: "dcs world", wrong: "'dcs world'"
- Mix: generic (dcs world, flight simulator) + specific (aircraft, map, mission type, campaign)
- Always include: dcs, dcs world, eagle dynamics, digital combat simulator
- Always include aircraft variants: e.g. for F-18 include: f18, f-18, fa-18, f/a-18c, hornet
- Always include: TheCylonPilot, cylon pilot
- If squadron video: include escuadron111, e111, escuadron virtual, simulacion aerea

CHAPTERS:
- Only include if you can reasonably infer time progression from the frames
- If uncertain, return empty array []
- Format times as "0:00", "1:30", "12:45"
"""

# ── Gemini API call ───────────────────────────────────────────────────────────

def call_gemini(frames_b64: list[str], prompt: str, model: str) -> str:
    """Call Gemini Vision API using only stdlib (no SDK needed)."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set.")

    url = (
        f"https://generativelanguage.googleapis.com/v1/models/"
        f"{model}:generateContent?key={api_key}"
    )

    parts = [{"text": prompt}]
    for frame_b64 in frames_b64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": frame_b64
            }
        })

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 4096
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"Gemini API error {e.code}: {body}")

    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response: {data}")

# ── Main analysis ─────────────────────────────────────────────────────────────

def generate_metadata(video_path: Path, user_context: str, config: dict, memory: dict) -> dict:
    print(f"\n{'─'*60}")
    print(f"  Processing: {video_path.name}")
    print(f"{'─'*60}")

    is_squadron = is_squadron_video(user_context)
    print(f"  Mode: {'🇪🇸 Squadron (E111)' if is_squadron else '🇬🇧 Solo / Campaign'}")

    print(f"  Extracting {config['frames_to_extract']} frames...")
    frames = extract_frames(video_path, config["frames_to_extract"])
    if not frames:
        print("  ✗ Could not extract frames. Check ffmpeg installation.")
        return {}

    model = config.get("model", "gemini-1.5-flash")
    prompt = build_prompt(user_context, config, is_squadron, memory)
    print(f"  Calling Gemini API ({model})...")

    try:
        raw = call_gemini(frames, prompt, model)
    except Exception as e:
        print(f"  ✗ API error: {e}")
        return {}

    # Strip markdown fences if model added them
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    raw = raw.strip()

    try:
        metadata = json.loads(raw)
        print("  ✓ Metadata generated")
        return metadata
    except json.JSONDecodeError as e:
        # Try to recover truncated JSON by closing open braces/brackets
        print(f"  ⚠ JSON truncated, attempting recovery...")
        recovered = _recover_json(raw)
        if recovered:
            print("  ✓ Recovered from truncated response")
            return recovered
        print(f"  ✗ JSON parse error: {e}")
        print(f"  Raw (first 500 chars): {raw[:500]}")
        return {}


def _recover_json(raw: str) -> dict:
    """Best-effort recovery of a truncated JSON string."""
    # Find the last complete field by trimming to the last comma or closing brace
    # Strategy: keep adding closing chars until it parses
    closers = {'{': '}', '[': ']'}
    stack = []
    last_good = 0

    for i, ch in enumerate(raw):
        if ch in ('{', '['):
            stack.append(ch)
        elif ch in ('}', ']'):
            if stack:
                stack.pop()
                last_good = i + 1

    # Try closing all open brackets
    suffix = ''.join(closers[c] for c in reversed(stack))
    candidates = [
        raw + suffix,           # close everything
        raw[:last_good],        # trim to last complete value
        raw.rstrip(',') + suffix  # remove trailing comma then close
    ]

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return {}

# ── Thumbnail generation ──────────────────────────────────────────────────────

def generate_thumbnail(frames_b64: list[str], metadata: dict, video_path: Path, config: dict) -> "Path | None":
    try:
        from PIL import Image, ImageDraw, ImageFont
        import io as _io
    except ImportError:
        print("  ⚠ Thumbnail skipped: pip install Pillow")
        return None

    if not frames_b64:
        return None

    # Pick frame at ~60% through — tends to show in-flight action over briefings
    idx = min(int(len(frames_b64) * 0.6), len(frames_b64) - 1)
    img = Image.open(_io.BytesIO(base64.b64decode(frames_b64[idx]))).convert("RGB")

    W, H = 1280, 720
    src_r, tgt_r = img.width / img.height, W / H
    if src_r > tgt_r:
        nw = int(img.height * tgt_r)
        img = img.crop(((img.width - nw) // 2, 0, (img.width + nw) // 2, img.height))
    else:
        nh = int(img.width / tgt_r)
        img = img.crop((0, (img.height - nh) // 2, img.width, (img.height + nh) // 2))
    img = img.resize((W, H), Image.LANCZOS).convert("RGBA")

    # Dark gradient over top third (title readability)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = ImageDraw.Draw(overlay)
    for y in range(290):
        alpha = int(210 * (1 - y / 290) ** 0.5)
        ov.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    # Dark bar at bottom
    ov.rectangle([(0, H - 88), (W, H)], fill=(0, 0, 0, 215))

    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    def load_font(size: int):
        for path in [
            "C:/Windows/Fonts/impact.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "/Library/Fonts/Impact.ttf",
            "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
        ]:
            try:
                return ImageFont.truetype(path, size)
            except (IOError, OSError):
                continue
        return ImageFont.load_default()

    def fit_text(text: str, max_w: int, start_size: int, min_size: int = 30):
        size = start_size
        while size >= min_size:
            font = load_font(size)
            bb = draw.textbbox((0, 0), text, font=font)
            if (bb[2] - bb[0]) <= max_w:
                return font, size
            size -= 4
        return load_font(min_size), min_size

    def outlined(x, y, text, font, fill, stroke=5):
        draw.text((x, y), text, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))

    # Build title lines: strip "DCS World | ", skip aircraft part (it's in the bottom bar)
    raw = metadata.get("title", "").strip()
    for prefix in ("DCS World | ", "DCS | "):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    parts = [p.strip().upper() for p in raw.split(" | ") if p.strip()]
    title_lines = parts[1:] if len(parts) > 1 else parts  # skip module part

    # Render title lines
    sizes   = [88, 68, 52]
    colors  = [(255, 215, 0), (255, 255, 255), (200, 200, 200)]
    y = 18
    for i, line in enumerate(title_lines[:3]):
        font, _ = fit_text(line, W - 80, sizes[min(i, len(sizes) - 1)])
        outlined(40, y, line, font, colors[min(i, len(colors) - 1)])
        bb = draw.textbbox((0, 0), line, font=font)
        y += (bb[3] - bb[1]) + 10

    # Bottom bar: aircraft · map
    aircraft = metadata.get("aircraft", "")
    map_name = metadata.get("map", "")
    bottom = "  ·  ".join(p for p in [aircraft, map_name] if p).upper()
    bot_font, _ = fit_text(bottom, W - 280, 34, 20)
    outlined(36, H - 72, bottom, bot_font, (255, 255, 255), stroke=3)

    # Channel handle (bottom-right)
    handle = f"@{config.get('channel_name', 'TheCylonPilot').lower()}"
    sm_font = load_font(22)
    bb = draw.textbbox((0, 0), handle, font=sm_font)
    outlined(W - (bb[2] - bb[0]) - 22, H - 66, handle, sm_font, (180, 180, 180), stroke=2)

    OUTPUT_PATH.mkdir(exist_ok=True)
    stem = video_path.stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    thumb_path = OUTPUT_PATH / f"{stem}_{ts}_thumb.jpg"
    img.save(thumb_path, "JPEG", quality=95)
    print(f"  [thumb] {thumb_path.name}")
    return thumb_path


def generate_thumbnail_on_demand(video_path: Path, metadata: dict, config: dict) -> "Path | None":
    """Extract one frame on demand and generate a thumbnail. Used by the web UI button."""
    tmp_path = Path(os.environ.get("TEMP", "/tmp")) / "dcs_thumb_frame.jpg"
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True, text=True, check=True
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except Exception as e:
        print(f"  Could not read duration for thumbnail: {e}")
        return None

    timestamp = duration * 0.6
    try:
        subprocess.run([
            "ffmpeg", "-y", "-ss", str(timestamp),
            "-i", str(video_path),
            "-vframes", "1", "-q:v", "2",
            "-vf", "scale=1920:-1",
            str(tmp_path)
        ], capture_output=True, check=True)
        with open(tmp_path, "rb") as f:
            frame_b64 = base64.standard_b64encode(f.read()).decode()
        tmp_path.unlink(missing_ok=True)
    except Exception as e:
        print(f"  Frame extraction failed for thumbnail: {e}")
        return None

    return generate_thumbnail([frame_b64], metadata, video_path, config)


# ── Output ────────────────────────────────────────────────────────────────────

def format_description(metadata: dict, config: dict) -> str:
    desc = metadata.get("description", "")
    links = config["default_links"]
    aircraft = metadata.get("aircraft", "").lower()

    if "f-18" in aircraft or "hornet" in aircraft or "f18" in aircraft:
        playlist = f"DCS F-18 Hornet: {links['dcs_f18_playlist']}"
    elif "a-10" in aircraft or "warthog" in aircraft:
        playlist = f"DCS A-10C: {links['dcs_a10c_playlist']}"
    elif "uh-1" in aircraft or "huey" in aircraft:
        playlist = f"DCS UH-1H Huey: {links['dcs_huey_playlist']}"
    else:
        playlist = (
            f"DCS F-18 Hornet: {links['dcs_f18_playlist']}\n"
            f"DCS A-10C: {links['dcs_a10c_playlist']}"
        )

    desc = desc.replace("[playlists relevantes]", playlist)
    desc = desc.replace("[relevant playlists]", playlist)
    return desc


def save_output(metadata: dict, video_path: Path, config: dict):
    OUTPUT_PATH.mkdir(exist_ok=True)
    stem = video_path.stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_PATH / f"{stem}_{timestamp}"

    metadata["description"] = format_description(metadata, config)

    json_path = base.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    txt_path = base.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{'═'*60}\n  DCS YouTube Metadata — TheCylonPilot\n")
        f.write(f"  Video: {video_path.name}\n")
        f.write(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'═'*60}\n\n")
        f.write(f"TITLE\n{'─'*40}\n{metadata.get('title','')}\n\n")
        f.write(f"DESCRIPTION\n{'─'*40}\n{metadata.get('description','')}\n\n")
        f.write(f"TAGS\n{'─'*40}\n{', '.join(metadata.get('tags', []))}\n\n")
        chapters = metadata.get("chapters", [])
        if chapters:
            f.write(f"CHAPTERS\n{'─'*40}\n")
            for ch in chapters:
                f.write(f"{ch['time']} {ch['label']}\n")
            f.write("\n")
        f.write(f"DETECTED\n{'─'*40}\n")
        f.write(f"Aircraft:     {metadata.get('aircraft','?')}\n")
        f.write(f"Map:          {metadata.get('map','?')}\n")
        f.write(f"Mission type: {metadata.get('mission_type','?')}\n")
        f.write(f"Language:     {metadata.get('language','?')}\n\n")
        if metadata.get("analysis_notes"):
            f.write(f"ANALYSIS NOTES\n{'─'*40}\n{metadata['analysis_notes']}\n")

    print(f"\n  📄 Saved: {txt_path.name}  +  {json_path.name}")
    return txt_path, json_path


def update_memory(metadata: dict, video_path: Path, memory: dict):
    memory["videos"].append({
        "date": datetime.now().strftime("%Y-%m-%d"),
        "filename": video_path.name,
        "title": metadata.get("title", ""),
        "language": metadata.get("language", ""),
        "aircraft": metadata.get("aircraft", ""),
        "map": metadata.get("map", ""),
        "mission_type": metadata.get("mission_type", "")
    })
    memory["videos"] = memory["videos"][-50:]
    save_memory(memory)


def print_preview(metadata: dict):
    print(f"\n{'═'*60}\n  PREVIEW\n{'═'*60}")
    print(f"\n  TITLE:\n  {metadata.get('title','')}\n")
    print(f"  DESCRIPTION (preview):\n  {metadata.get('description','')[:300]}...\n")
    tags = metadata.get("tags", [])
    print(f"  TAGS ({len(tags)}): {', '.join(tags[:10])}{'...' if len(tags)>10 else ''}\n")
    for ch in metadata.get("chapters", []):
        print(f"    {ch['time']} — {ch['label']}")
    print()

# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="DCS YouTube Metadata Generator — TheCylonPilot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dcs_meta.py C:\\Videos\\DCS\\mission.mp4
  python dcs_meta.py C:\\Videos\\DCS\\mission.mkv -c "A-10C II Outpost Campaign - Mission 3"
  python dcs_meta.py C:\\Videos\\DCS\\op.mp4 -c "Escuadrón 111 - Operación Trueno - SEAD support"
  python dcs_meta.py C:\\Videos\\DCS\\ --batch
        """
    )
    parser.add_argument("path", help="Video file or folder path")
    parser.add_argument("-c", "--context", default="",
                        help="Mission context: campaign name, mission number, title, etc.")
    parser.add_argument("--batch", action="store_true",
                        help="Process all video files in a folder")
    parser.add_argument("--no-preview", action="store_true",
                        help="Skip terminal preview")
    args = parser.parse_args()

    config = load_config()
    memory = load_memory()

    if not os.environ.get("GEMINI_API_KEY"):
        print("\n✗ GEMINI_API_KEY not set.")
        print("  Get a free key at: https://aistudio.google.com/app/apikey")
        print("    Windows:   set GEMINI_API_KEY=AIza...")
        print("    Mac/Linux: export GEMINI_API_KEY=AIza...")
        sys.exit(1)

    input_path = Path(args.path)
    video_extensions = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

    if args.batch or input_path.is_dir():
        videos = [f for f in input_path.iterdir() if f.suffix.lower() in video_extensions]
        if not videos:
            print(f"No video files found in {input_path}")
            sys.exit(1)
        print(f"\nFound {len(videos)} video(s) in {input_path}")
    else:
        if not input_path.exists():
            print(f"✗ File not found: {input_path}")
            sys.exit(1)
        videos = [input_path]

    for video in sorted(videos):
        metadata = generate_metadata(video, args.context, config, memory)
        if not metadata:
            print(f"  ✗ Skipping {video.name}\n")
            continue
        if not args.no_preview:
            print_preview(metadata)
        save_output(metadata, video, config)
        update_memory(metadata, video, memory)

    print(f"\n✓ Done. Check the output/ folder.\n")


if __name__ == "__main__":
    main()
