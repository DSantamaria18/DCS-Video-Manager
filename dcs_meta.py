#!/usr/bin/env python3
"""
DCS YouTube Metadata Generator — TheCylonPilot
Analyzes DCS World video files and generates optimized YouTube metadata.
Uses Google Gemini Vision API (gemini-1.5-flash) — free tier: 1500 req/day.
"""

import os
import re
import sys
import json
import base64
import subprocess
import argparse
import threading
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from collections import Counter

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config" / "config.json"
MEMORY_PATH = Path(__file__).parent / "memory" / "history.json"
OUTPUT_PATH = Path(__file__).parent / "output"

DEFAULT_CONFIG = {
    "channel_name": "TheCylonPilot",
    "channel_description": "DCS World simulation — learning through mistakes, F/A-18C Hornet main module, also F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache.",
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

# Per-module data injected into the Gemini prompt for accurate aircraft identification
MODULE_PROFILES = {
    "F/A-18C Hornet": {
        "cockpit": "MPCD/DDI multifunction displays, digital UFC, HUD with carrier approach symbology",
        "missions": "BVR, CAS, SEAD, AAR, carrier ops",
        "weapons": "AIM-120 AMRAAM, AIM-9X, AGM-88 HARM, JDAM, GBU-12, AGM-65 Maverick",
        "tags": ["f18", "f-18", "fa-18", "f/a-18c", "hornet"],
    },
    "F-16C Viper": {
        "cockpit": "Paired round MFDs, bubble canopy, HARM targeting system interface",
        "missions": "SEAD, BVR, CAS, strike",
        "weapons": "AIM-120 AMRAAM, AIM-9X, AGM-88 HARM, JDAM, CBU",
        "tags": ["f16", "f-16", "viper", "f16c", "f-16c"],
    },
    "F-14 Tomcat": {
        "cockpit": "AWG-9 TCS screen, analogue gauges, RIO rear-seat instruments, variable-sweep wings",
        "missions": "BVR intercept, fleet defense, LANTIRN strike, TARPS recon",
        "weapons": "AIM-54 Phoenix, AIM-7 Sparrow, AIM-9 Sidewinder, LANTIRN, unguided bombs",
        "tags": ["f14", "f-14", "tomcat", "f14b", "f-14b", "phoenix"],
    },
    "UH-1H Huey": {
        "cockpit": "Vietnam-era analogue gauges, twin collective/cyclic layout, door gunner positions",
        "missions": "CAS, CSAR, troop transport, sling load",
        "weapons": "M134 minigun, M60 door guns, 2.75-in rockets",
        "tags": ["uh1h", "uh-1h", "huey", "helicopter dcs"],
    },
    "A-10C Warthog": {
        "cockpit": "MFCDs with DSMS/TGP pages, attack HUD with weapons-delivery symbology",
        "missions": "CAS, FAC, anti-armour, SEAD",
        "weapons": "GAU-8 Avenger cannon, AGM-65 Maverick, JDAM, GBU-12, AIM-9",
        "tags": ["a10c", "a-10c", "warthog", "a10", "a-10", "thunderbolt ii"],
    },
    "C-130J Hercules": {
        "cockpit": "Flat-panel glass cockpit with MFDs, high-wing transport layout, four turboprop engines",
        "missions": "Strategic airlift, AAR tanking, airdrop, LAPES, low-level ops",
        "weapons": "None — transport/tanker aircraft",
        "tags": ["c130j", "c-130j", "hercules", "c130", "super hercules"],
    },
    "AH-64D Apache": {
        "cockpit": "IHADSS helmet-sight overlay, TADS/PNVS targeting display, tandem CPG/pilot seats",
        "missions": "CAS, anti-armour, armed recon, NOE, escort",
        "weapons": "AGM-114 Hellfire, Hydra 70 rockets, M230 30mm chain gun",
        "tags": ["ah64d", "ah-64d", "apache", "ah64", "ah-64", "longbow"],
    },
}

# Lock for thread-safe memory read-modify-write in concurrent analysis jobs
_memory_lock = threading.Lock()

# Font search paths for thumbnail overlay (Impact preferred, Arial Bold fallback)
_FONT_PATHS = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Impact.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
]

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


def _get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds using ffprobe. Raises on failure."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
        capture_output=True, text=True, check=True
    )
    return float(json.loads(result.stdout)["format"]["duration"])

# ── Frame extraction ─────────────────────────────────────────────────────────

def extract_frames(video_path: Path, n_frames: int = 8) -> list[str]:
    """Extract N evenly-spaced frames via ffmpeg. Returns list of base64 JPEG strings."""
    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))

    try:
        duration = _get_video_duration(video_path)
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

# ── Series / campaign detection ──────────────────────────────────────────────

# Matches "- Mission 3", "– Episode 7", "Part 2", "Ep. 4", "Cap. 5" etc.
_EPISODE_RE = re.compile(
    r'[-–\s]+(?:mission|episode|ep\.?|part|capítulo|cap\.?)\s*(\d+)',
    re.IGNORECASE
)


def _detect_series(user_context: str, history: dict) -> dict | None:
    """Detect campaign name and episode number from user_context.

    Returns a dict with keys `campaign`, `episode`, `prev_episodes` (last 3
    matching history entries), or None if no episode marker is found.
    Each prev_episode entry has `title`, `date`, and optionally `url`
    (when a video_id was stored after upload).
    """
    if not user_context:
        return None

    m = _EPISODE_RE.search(user_context)
    if not m:
        return None

    episode_num = int(m.group(1))
    campaign_name = user_context[:m.start()].strip().strip("-–").strip()
    if not campaign_name:
        return None

    campaign_lower = campaign_name.lower()
    prev_episodes = []
    for v in history.get("videos", []):
        if campaign_lower in v.get("title", "").lower():
            ep_info = {"title": v.get("title", ""), "date": v.get("date", "")}
            if v.get("video_id"):
                ep_info["url"] = f"https://youtu.be/{v['video_id']}"
            prev_episodes.append(ep_info)

    return {
        "campaign": campaign_name,
        "episode": episode_num,
        "prev_episodes": prev_episodes[-3:],
    }


def _aircraft_series_suggestions(history: dict, min_count: int = 3) -> list[tuple[str, int]]:
    """Return (aircraft, count) pairs from history with count >= min_count, most common first."""
    counts = Counter(
        v.get("aircraft", "").strip()
        for v in history.get("videos", [])
        if v.get("aircraft", "").strip()
    )
    return [(a, n) for a, n in counts.most_common() if n >= min_count]


# ── Prompt ───────────────────────────────────────────────────────────────────

def _video_length_category(duration_seconds: float) -> str:
    """Return 'short' (<10 min), 'medium' (10-30 min), or 'long' (>30 min)."""
    if duration_seconds < 600:
        return "short"
    if duration_seconds < 1800:
        return "medium"
    return "long"


def _build_description_rules(is_squadron: bool, category: str) -> str:
    """Return length-adapted description template for the Gemini prompt."""
    if category == "short":
        if is_squadron:
            return """\
DESCRIPTION RULES — SHORT VIDEO (<10 min) — "quick tactical breakdown":
[1 frase directa y contundente describiendo la acción principal]

✈ Aeronave: [nombre]
🗺 Mapa: [mapa]
🎯 Tipo de misión: [tipo]
👥 Escuadrón: Escuadrón 111 (E111) — https://www.escuadron111.eu/

[1-2 frases: el momento clave o conclusión táctica — qué salió bien o mal]

📺 MÁS VÍDEOS DCS
[playlists relevantes]

🔗 SÍGUENOS
Twitter: https://twitter.com/thecylonpilot
Twitch: https://www.twitch.tv/thecylonpilot

#DCSWorld #[Aeronave] #[tags relevantes]"""
        else:
            return """\
DESCRIPTION RULES — SHORT VIDEO (<10 min) — "quick tactical breakdown":
[1 punchy sentence — lead with the action, no buildup]

✈ Aircraft: [full name]
🗺 Map: [map name]
🎯 Mission type: [CAS / BVR / AAR / SEAD / Strike / Training / etc.]

[1-2 sentences: the key moment or takeaway — what went right or wrong]

📺 MORE DCS VIDEOS
[relevant playlists]

🔗 FOLLOW
Twitter: [link]
Twitch: [link]
Support: [link]

#DCSWorld #[Aircraft] #[relevant tags]"""

    if category == "medium":
        if is_squadron:
            return """\
DESCRIPTION RULES — MEDIUM VIDEO (10-30 min) — "full training video":
[Hook: 1-2 frases describiendo la misión con tono de informe]

✈ Aeronave: [nombre]
🗺 Mapa: [mapa]
🎯 Tipo de misión: [tipo]
👥 Escuadrón: Escuadrón 111 (E111) — https://www.escuadron111.eu/

[2-3 frases narrando la misión: fases principales, momentos clave, errores o éxitos]

---
🕐 CAPÍTULOS
[si el video dura más de 5 min]

---
📺 MÁS VÍDEOS DCS
[playlists relevantes]

🔗 SÍGUENOS
Twitter: https://twitter.com/thecylonpilot
Twitch: https://www.twitch.tv/thecylonpilot

#DCSWorld #[Aeronave] #[tags relevantes]"""
        else:
            return """\
DESCRIPTION RULES — MEDIUM VIDEO (10-30 min) — "full training video":
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

#DCSWorld #[Aircraft] #[relevant tags]"""

    # long
    if is_squadron:
        return """\
DESCRIPTION RULES — LONG VIDEO (>30 min) — "complete mission debrief":
[2 frases de hook: qué era la misión + el momento culminante o resultado]

✈ Aeronave: [nombre]
🗺 Mapa: [mapa]
🎯 Tipo de misión: [tipo]
👥 Escuadrón: Escuadrón 111 (E111) — https://www.escuadron111.eu/

[Resumen de misión: 1 frase de overview]

[3-4 frases con desglose detallado: fases de la misión, compromisos clave, errores y éxitos, momentos memorables]

💬 ¿Cómo lo habrías hecho tú? Déjanos tu análisis en los comentarios.

---
🕐 CAPÍTULOS
[OBLIGATORIO para vídeos largos — incluir siempre aunque sea con tiempos aproximados]

---
📺 MÁS VÍDEOS DCS
[playlists relevantes]

🔗 SÍGUENOS
Twitter: https://twitter.com/thecylonpilot
Twitch: https://www.twitch.tv/thecylonpilot

#DCSWorld #[Aeronave] #[tags relevantes]"""
    else:
        return """\
DESCRIPTION RULES — LONG VIDEO (>30 min) — "complete mission debrief":
[2-sentence hook: what the mission was + the dramatic moment or outcome]

✈ Aircraft: [full name]
🗺 Map: [map name]
🎯 Mission type: [CAS / BVR / AAR / SEAD / Strike / Training / etc.]
📋 Campaign: [if applicable]

[Mission summary: 1-sentence overview of the full sortie]

[3-4 sentences of detailed narrative: mission phases, key engagements, mistakes and wins, memorable moments]

💬 Drop a comment with your tactics — what would you have done differently?

---
🕐 CHAPTERS
[MANDATORY for long videos — always include, use rough time estimates if needed]

---
📺 MORE DCS VIDEOS
[relevant playlists]

🔗 FOLLOW
Twitter: [link]
Twitch: [link]
Support: [link]

#DCSWorld #[Aircraft] #[relevant tags]"""


def _build_module_guide() -> str:
    lines = []
    for module, data in MODULE_PROFILES.items():
        tag_str = ", ".join(data["tags"])
        lines.append(
            f"- {module}: cockpit={data['cockpit']} | "
            f"missions={data['missions']} | weapons={data['weapons']} | "
            f"tags={tag_str}"
        )
    return "\n".join(lines)


def build_prompt(user_context: str, config: dict, is_squadron: bool, memory: dict,
                 duration_seconds: float = None, series_context: dict = None,
                 aircraft_suggestions: list = None) -> str:
    recent = memory["videos"][-5:] if memory["videos"] else []
    memory_block = ""
    if recent:
        memory_block = "\n\nRECENT VIDEOS (for style consistency):\n"
        for v in recent:
            memory_block += f"- [{v['date']}] {v['title']} ({v['language']})\n"

    series_block = ""
    if series_context:
        series_block = f"\n\nSERIES CONTEXT — this video is part of a campaign:\n"
        series_block += f"- Campaign: {series_context['campaign']}\n"
        series_block += f"- Episode: {series_context['episode']}\n"
        series_block += (
            "- In the title use episode numbering, e.g. "
            f"\"... | Ep.{series_context['episode']} | ...\"\n"
        )
        if series_context["prev_episodes"]:
            series_block += "- Previous episodes (link in description if URLs are present):\n"
            for ep in series_context["prev_episodes"]:
                line = f"  [{ep['date']}] {ep['title']}"
                if ep.get("url"):
                    line += f" — {ep['url']}"
                series_block += line + "\n"

    aircraft_block = ""
    if aircraft_suggestions:
        aircraft_block = "\n\nAIRCRAFT PLAYLIST SUGGESTIONS:\n"
        for aircraft, count in aircraft_suggestions:
            aircraft_block += (
                f"- {aircraft} ({count} videos in history) — "
                "suggest the relevant playlist or series grouping in the description.\n"
            )

    category = _video_length_category(duration_seconds) if duration_seconds is not None else "medium"
    duration_hint = ""
    if duration_seconds is not None:
        minutes = int(duration_seconds // 60)
        duration_hint = f"\nVIDEO DURATION: ~{minutes} min — apply the {category.upper()} video format below."

    if is_squadron:
        lang_instructions = """LANGUAGE: Spanish (Spain). Formal but warm tone.
This is a squadron mission video with Escuadrón 111 (E111), a veteran Spanish virtual aviation community with 25+ years of history.
Tone: mission report style, proud of the team, mention callsigns/roles if visible in the video."""
    else:
        lang_instructions = """LANGUAGE: English. Tone: enthusiastic learner, honest about mistakes, technically interested.
This is a solo/campaign video. The pilot is learning DCS and shares both successes and failures to help other beginners."""

    description_rules = _build_description_rules(is_squadron, category)

    chapters_rule = {
        "short":  "Do NOT include chapters — video is too short (<10 min). Return empty array [].",
        "medium": "Include chapters only if you can reasonably infer time progression from the frames. If uncertain, return [].",
        "long":   "ALWAYS include chapters — mandatory for long videos. Generate chapters even with rough time estimates.",
    }[category]

    return f"""You are a YouTube metadata specialist for the DCS World simulation channel "TheCylonPilot".

CHANNEL IDENTITY:
- Creator: Spanish simmer, 47 years old, IT professional
- Main module: F/A-18C Hornet | Also flies: F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache
- Philosophy: Learning through mistakes, helping beginners
- Squadron: Escuadrón 111 (E111) — veteran Spanish virtual aviation community

{lang_instructions}{duration_hint}

USER CONTEXT FOR THIS VIDEO:
{user_context if user_context else "(none provided — infer everything from video frames)"}
{memory_block}{series_block}{aircraft_block}

MODULE IDENTIFICATION GUIDE:
Use cockpit details in the frames to identify the aircraft, then apply the matching mission context and tags below.

{_build_module_guide()}

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
  "campaign": "...",
  "analysis_notes": "brief explanation of what you saw in the frames"
}}

TITLE RULES:
- English solo: "DCS World | [Aircraft] | [Mission/Action] | [Campaign if known]"
  Example: "DCS World | F/A-18C Hornet | Night SEAD Strike | Raven One Campaign"
- Spanish squadron: "DCS World | [Aeronave] | [Nombre Misión] | E111"
  Example: "DCS World | F/A-18C Hornet | Operación Trueno | E111"
- Max 70 characters. No clickbait. No ALL CAPS.

{description_rules}

TAGS RULES:
- 30-40 tags total
- Return tags as plain strings with NO surrounding quotes — correct: "dcs world", wrong: "'dcs world'"
- Mix: generic (dcs world, flight simulator) + specific (aircraft, map, mission type, campaign)
- Always include: dcs, dcs world, eagle dynamics, digital combat simulator
- Always include aircraft variants: e.g. for F-18 include: f18, f-18, fa-18, f/a-18c, hornet
- Always include: TheCylonPilot, cylon pilot
- If squadron video: include escuadron111, e111, escuadron virtual, simulacion aerea

CHAPTERS:
- {chapters_rule}
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

def generate_metadata(video_path: Path, user_context: str, config: dict, memory: dict,
                      frames: list = None) -> dict:
    """Analyse a video and return YouTube metadata via Gemini.

    Pass `frames` (list of base64 JPEG strings) to skip re-extraction when
    the caller has already extracted frames (avoids running ffmpeg twice).
    """
    print(f"\n{'─'*60}")
    print(f"  Processing: {video_path.name}")
    print(f"{'─'*60}")

    is_squadron = is_squadron_video(user_context)
    print(f"  Mode: {'🇪🇸 Squadron (E111)' if is_squadron else '🇬🇧 Solo / Campaign'}")

    try:
        duration_seconds = _get_video_duration(video_path)
        minutes = int(duration_seconds // 60)
        category = _video_length_category(duration_seconds)
        print(f"  Duration: {minutes} min → {category} video format")
    except Exception:
        duration_seconds = None
        print("  Duration: unknown — using medium format")

    series_context = _detect_series(user_context, memory)
    if series_context:
        print(f"  Series: {series_context['campaign']} — Ep.{series_context['episode']}")

    aircraft_suggestions = _aircraft_series_suggestions(memory)

    if frames is None:
        print(f"  Extracting {config['frames_to_extract']} frames...")
        frames = extract_frames(video_path, config["frames_to_extract"])
    if not frames:
        print("  ✗ Could not extract frames. Check ffmpeg installation.")
        return {}

    model = config.get("model", "gemini-1.5-flash")
    prompt = build_prompt(user_context, config, is_squadron, memory, duration_seconds,
                          series_context, aircraft_suggestions)
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

def _load_font(size: int):
    """Load Impact (or Arial Bold fallback) at the given point size."""
    from PIL import ImageFont
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()


def _fit_text(draw, text: str, max_w: int, start_size: int, min_size: int = 30):
    """Return the largest font that fits `text` within `max_w` pixels."""
    size = start_size
    while size >= min_size:
        font = _load_font(size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return font
        size -= 4
    return _load_font(min_size)


def _score_frame(img) -> float:
    """Score a PIL image for thumbnail suitability. Higher = better.

    Caller must have already imported PIL (Image, ImageFilter, ImageStat).
    """
    from PIL import Image, ImageFilter, ImageStat
    small = img.resize((320, 180), Image.LANCZOS)
    gray = small.convert("L")
    sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).mean[0]
    brightness = ImageStat.Stat(gray).mean[0]
    # Penalise frames that are too dark (<70) or too washed-out (>190)
    b_factor = max(0.15, 1.0 - max(0.0, abs(brightness - 130) - 60) / 70.0)
    colorfulness = sum(ImageStat.Stat(small).stddev)
    return sharpness * b_factor + colorfulness * 0.25


def _grade_frame(img):
    """Cinematic colour grade: +30% saturation, +15% contrast, warm push.

    Caller must have already imported PIL (ImageEnhance, Image).
    """
    from PIL import ImageEnhance, Image as _Img
    img = ImageEnhance.Color(img).enhance(1.30)
    img = ImageEnhance.Contrast(img).enhance(1.15)
    r, g, b = img.split()
    r = r.point(lambda x: min(255, int(x * 1.05)))
    b = b.point(lambda x: int(x * 0.94))
    return _Img.merge("RGB", (r, g, b))


def _apply_thumbnail_overlay(img, metadata: dict, config: dict):
    """Apply YouTube-style overlay to a PIL RGB image (1280×720).

    Layout: full frame visible, bottom gradient for text readability,
    title lines above the info bar (bottom-up), solid bottom info bar.
    """
    from PIL import Image, ImageDraw

    W, H = 1280, 720
    if img.size != (W, H):
        src_r, tgt_r = img.width / img.height, W / H
        if src_r > tgt_r:
            nw = int(img.height * tgt_r)
            img = img.crop(((img.width - nw) // 2, 0, (img.width + nw) // 2, img.height))
        else:
            nh = int(img.width / tgt_r)
            img = img.crop((0, (img.height - nh) // 2, img.width, (img.height + nh) // 2))
        img = img.resize((W, H), Image.LANCZOS)

    img = img.convert("RGBA")
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ov = ImageDraw.Draw(overlay)
    # Bottom gradient: transparent at H-320, semi-opaque at H-88 (title text area)
    grad_top, grad_bot = H - 320, H - 85
    for y in range(grad_top, grad_bot + 1):
        t = (y - grad_top) / (grad_bot - grad_top)
        ov.line([(0, y), (W, y)], fill=(0, 0, 0, int(190 * t ** 1.3)))
    # Solid bottom info bar
    ov.rectangle([(0, H - 88), (W, H)], fill=(0, 0, 0, 215))
    img = Image.alpha_composite(img, overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    def outlined(x, y, text, font, fill, stroke=5):
        draw.text((x, y), text, font=font, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))

    raw = metadata.get("title", "").strip()
    for prefix in ("DCS World | ", "DCS | "):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    parts = [p.strip().upper() for p in raw.split(" | ") if p.strip()]
    title_lines = parts[1:] if len(parts) > 1 else parts

    sizes  = [88, 68, 52]
    colors = [(255, 215, 0), (255, 255, 255), (200, 200, 200)]

    # Pre-measure all lines, then place bottom-up above the info bar
    measured = []
    for i, line in enumerate(title_lines[:3]):
        font = _fit_text(draw, line, W - 80, sizes[min(i, len(sizes) - 1)])
        bb = draw.textbbox((0, 0), line, font=font)
        measured.append((line, font, bb[3] - bb[1], colors[min(i, len(colors) - 1)]))

    y_cursor = H - 100
    positions = []
    for line, font, h, color in reversed(measured):
        positions.insert(0, (line, font, y_cursor - h, color))
        y_cursor = y_cursor - h - 10

    for line, font, y, color in positions:
        outlined(40, y, line, font, color)

    bottom = "  ·  ".join(p for p in [metadata.get("aircraft", ""), metadata.get("map", "")] if p).upper()
    outlined(36, H - 72, bottom, _fit_text(draw, bottom, W - 280, 34, 20), (255, 255, 255), stroke=3)

    handle = f"@{config.get('channel_name', 'TheCylonPilot').lower()}"
    sm_font = _load_font(22)
    bb = draw.textbbox((0, 0), handle, font=sm_font)
    outlined(W - (bb[2] - bb[0]) - 22, H - 66, handle, sm_font, (180, 180, 180), stroke=2)

    return img


def _save_thumbnail(img, video_path: Path, suffix: str) -> Path:
    """Save thumbnail JPEG under 2 MB, reducing quality if needed."""
    import io
    OUTPUT_PATH.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_PATH / f"{video_path.stem}_{ts}_{suffix}.jpg"
    for quality in (90, 80, 70, 60, 50):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        if buf.tell() < 2 * 1024 * 1024:
            path.write_bytes(buf.getvalue())
            print(f"  [thumb] {path.name} ({buf.tell() // 1024} KB, q={quality})")
            return path
    path.write_bytes(buf.getvalue())
    return path


def generate_thumbnail_on_demand(metadata: dict, video_path: Path, config: dict,
                                  n_candidates: int = 4) -> list[Path]:
    """Extract candidate frames from the video, score them, and return thumbnail Paths.

    Samples n_candidates+2 frames across 18-78% of the video, picks the
    n_candidates best-scoring ones (sharpness + brightness + colorfulness),
    applies colour grading and the text overlay, and returns them sorted
    best-first so index 0 is the recommended thumbnail.
    """
    try:
        from PIL import Image
        import io as _io
    except ImportError:
        raise RuntimeError("Pillow not installed: pip install Pillow")

    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))

    try:
        duration = _get_video_duration(video_path)
    except Exception as e:
        raise RuntimeError(f"ffprobe failed: {e}")

    n_sample = n_candidates + 2
    offsets = [0.18 + i * 0.60 / (n_sample - 1) for i in range(n_sample)]

    scored = []
    for idx, offset in enumerate(offsets):
        tmp_path = tmp_dir / f"dcs_thumb_{idx}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(duration * offset),
                "-i", str(video_path),
                "-vframes", "1", "-q:v", "2",
                "-vf", "scale=1280:-1",
                str(tmp_path)
            ], capture_output=True, check=True)
            img_bytes = tmp_path.read_bytes()
            tmp_path.unlink(missing_ok=True)
            img = Image.open(_io.BytesIO(img_bytes)).convert("RGB")
            scored.append((_score_frame(img), img_bytes))
        except Exception:
            continue

    if not scored:
        raise RuntimeError("Could not extract any frames from video")

    scored.sort(key=lambda x: x[0], reverse=True)

    paths = []
    for i, (_, img_bytes) in enumerate(scored[:n_candidates]):
        img = Image.open(_io.BytesIO(img_bytes)).convert("RGB")
        img = _grade_frame(img)
        img = _apply_thumbnail_overlay(img, metadata, config)
        paths.append(_save_thumbnail(img, video_path, f"thumb_{i}"))

    return paths


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


def update_memory(metadata: dict, video_path: Path) -> None:
    """Append analysis result to history. Thread-safe: re-reads disk under lock."""
    with _memory_lock:
        memory = load_memory()
        memory["videos"].append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "filename": video_path.name,
            "title": metadata.get("title", ""),
            "language": metadata.get("language", ""),
            "aircraft": metadata.get("aircraft", ""),
            "map": metadata.get("map", ""),
            "mission_type": metadata.get("mission_type", ""),
            "campaign": metadata.get("campaign", ""),
            "video_id": "",
        })
        memory["videos"] = memory["videos"][-50:]
        save_memory(memory)


def update_memory_video_id(filename: str, video_id: str) -> None:
    """Patch the most recent history entry matching filename with the YouTube video_id."""
    with _memory_lock:
        memory = load_memory()
        for v in reversed(memory["videos"]):
            if v.get("filename") == filename:
                v["video_id"] = video_id
                break
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
        update_memory(metadata, video)

    print(f"\n✓ Done. Check the output/ folder.\n")


if __name__ == "__main__":
    main()
