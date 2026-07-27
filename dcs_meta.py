#!/usr/bin/env python3
"""
DCS YouTube Metadata Generator — TheCylonPilot
Analyzes DCS World video files and generates optimized YouTube metadata.
Uses Google Gemini Vision API (gemini-1.5-flash) — free tier: 1500 req/day.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────────────
CONFIG_PATH = Path(__file__).parent / "config" / "config.json"
# Discord secrets live in a separate, gitignored file (SEC-01) — config.json is
# tracked by git, and a bot token or webhook URL must never end up in a commit.
SECRETS_PATH = Path(__file__).parent / "config" / "secrets.json"
SECRET_KEYS = {"discord_webhook_url", "discord_bot_token", "discord_channel_id"}
MEMORY_PATH = Path(__file__).parent / "memory" / "history.json"
ANALYSIS_CACHE_PATH = Path(__file__).parent / "memory" / "analysis_cache.json"
OUTPUT_PATH = Path(__file__).parent / "output"

# Exceptions _get_video_duration() can raise (see its docstring): ffprobe missing
# (wrapped as RuntimeError), non-zero exit, malformed JSON, or a missing/non-numeric
# duration field.
_DURATION_ERRORS = (RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError)

# Exceptions call_gemini() can raise (see its docstring): no API key, HTTP/network
# failure, or a malformed API response — all surfaced as OSError/RuntimeError/JSONDecodeError.
_GEMINI_ERRORS = (OSError, RuntimeError, json.JSONDecodeError)

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
    "model": "gemini-2.5-flash",
    "description_templates": {},
    "recordings_folder": ""
}

# Discord secrets (SEC-01) — see SECRETS_PATH above.
DEFAULT_SECRETS = {
    "discord_webhook_url": "",
    "discord_bot_token": "",
    "discord_channel_id": ""
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

# ── Config & memory ──────────────────────────────────────────────────────────

def load_secrets():
    """Load secrets.json, creating it with defaults if absent. Never tracked by git (SEC-01)."""
    SECRETS_PATH.parent.mkdir(exist_ok=True)
    if SECRETS_PATH.exists():
        with open(SECRETS_PATH, encoding="utf-8") as f:
            return {**DEFAULT_SECRETS, **json.load(f)}
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SECRETS, f, indent=2, ensure_ascii=False)
    return DEFAULT_SECRETS


def save_secrets(secrets):
    """Persist secrets.json. Never tracked by git (SEC-01)."""
    SECRETS_PATH.parent.mkdir(exist_ok=True)
    with open(SECRETS_PATH, "w", encoding="utf-8") as f:
        json.dump(secrets, f, indent=2, ensure_ascii=False)


def load_config():
    """Load config.json, creating it with defaults if absent.

    Discord secrets are merged in from secrets.json (SEC-01) so callers keep
    seeing one flat config dict; only load_config()/save_config() know the
    storage is split.
    """
    CONFIG_PATH.parent.mkdir(exist_ok=True)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = {**DEFAULT_CONFIG, **json.load(f)}
    else:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
        cfg = dict(DEFAULT_CONFIG)
    return {**cfg, **load_secrets()}


def load_memory():
    """Load history.json, returning an empty video list if absent."""
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    if MEMORY_PATH.exists():
        with open(MEMORY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"videos": []}


def save_memory(memory):
    """Persist memory dict to history.json."""
    MEMORY_PATH.parent.mkdir(exist_ok=True)
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(memory, f, indent=2, ensure_ascii=False)


_analysis_cache_lock = threading.Lock()


def load_analysis_cache() -> dict:
    """Load analysis_cache.json, returning an empty cache if absent."""
    ANALYSIS_CACHE_PATH.parent.mkdir(exist_ok=True)
    if ANALYSIS_CACHE_PATH.exists():
        with open(ANALYSIS_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_analysis_cache(cache: dict) -> None:
    """Persist the analysis cache dict to analysis_cache.json."""
    ANALYSIS_CACHE_PATH.parent.mkdir(exist_ok=True)
    with open(ANALYSIS_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def get_cached_metadata(video_path: Path) -> dict | None:
    """Return cached Gemini metadata for video_path if size and mtime still match.

    Keyed by resolved absolute path. A stale entry (file replaced/re-encoded, so size
    or mtime changed) is treated as a miss — the caller re-analyses and overwrites it.
    """
    stat = video_path.stat()
    with _analysis_cache_lock:
        entry = load_analysis_cache().get(str(video_path.resolve()))
    if not entry:
        return None
    if entry.get("size") != stat.st_size or entry.get("mtime") != stat.st_mtime:
        return None
    return entry.get("metadata")


def set_cached_metadata(video_path: Path, metadata: dict) -> None:
    """Store metadata for video_path, keyed by resolved path + current size/mtime."""
    stat = video_path.stat()
    with _analysis_cache_lock:
        cache = load_analysis_cache()
        cache[str(video_path.resolve())] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "metadata": metadata,
            "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005 — hora local de la máquina, coherente con el resto de timestamps del proyecto
        }
        save_analysis_cache(cache)


def is_squadron_video(user_context: str) -> bool:
    """Return True if user_context contains a squadron keyword (E111 or similar)."""
    ctx = user_context.lower()
    return any(k in ctx for k in SQUADRON_KEYWORDS)


def _get_video_duration(video_path: Path) -> float:
    """Return video duration in seconds using ffprobe. Raises on failure."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)],
            capture_output=True, text=True, check=True
        )
        return float(json.loads(result.stdout)["format"]["duration"])
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — install ffmpeg (https://ffmpeg.org)")


def _seconds_to_chapter_time(s: float) -> str:
    """Convert seconds to 'M:SS' chapter timestamp string."""
    return f"{int(s // 60)}:{int(s % 60):02d}"


def detect_audio_chapters(
    video_path: Path,
    duration_seconds: float | None = None,
    noise_db: int = -30,
    min_silence_s: float = 3.0,
    min_gap_s: float = 60.0,
) -> list[str]:
    """Detect chapter boundaries from audio silences via ffmpeg silencedetect.

    Returns 'M:SS' timestamp strings starting with '0:00'. Returns ['0:00'] alone
    if detection fails or no usable silences are found.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path),
                "-af", f"silencedetect=noise={noise_db}dB:duration={min_silence_s}",
                "-f", "null", "-",
            ],
            capture_output=True, text=True, check=False,
        )
        stderr = result.stderr
    except (FileNotFoundError, OSError):
        return ["0:00"]

    # Parse "silence_end: X.XXX | silence_duration: Y" lines from stderr
    silence_ends: list[float] = []
    for line in stderr.splitlines():
        if "silence_end:" not in line:
            continue
        try:
            t = float(line.split("silence_end:")[1].split("|")[0].strip())
            silence_ends.append(t)
        except (ValueError, IndexError):
            continue

    # Build chapter starts: always 0:00, then each silence_end that is ≥ min_gap_s
    # from the previous marker and not in the last 10% of the video.
    tail_cutoff = duration_seconds * 0.90 if duration_seconds else float("inf")
    markers: list[float] = [0.0]
    for t in silence_ends:
        if t - markers[-1] >= min_gap_s and t <= tail_cutoff:
            markers.append(t)

    # Cap at 8 total markers (chapters beyond that are rarely useful in YouTube)
    markers = markers[:8]

    return [_seconds_to_chapter_time(t) for t in markers]


# ── Frame extraction ─────────────────────────────────────────────────────────

def extract_frames(video_path: Path, n_frames: int = 8) -> list[str]:
    """Extract N evenly-spaced frames via ffmpeg. Returns list of base64 JPEG strings."""
    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))

    try:
        duration = _get_video_duration(video_path)
    except _DURATION_ERRORS as e:
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
        except (subprocess.CalledProcessError, OSError) as e:
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


VALID_TEMPLATE_KEYS = {
    "en_short", "en_medium", "en_long",
    "es_short", "es_medium", "es_long",
}


_DESCRIPTION_TEMPLATES: dict[str, str] = {
    "en_short": """\
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
Buy Me a Coffee: [link]

#DCSWorld #[Aircraft] #[relevant tags]""",

    "en_medium": """\
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
Buy Me a Coffee: [link]

#DCSWorld #[Aircraft] #[relevant tags]""",

    "en_long": """\
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
Buy Me a Coffee: [link]

#DCSWorld #[Aircraft] #[relevant tags]""",

    "es_short": """\
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

#DCSWorld #[Aeronave] #[tags relevantes]""",

    "es_medium": """\
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

#DCSWorld #[Aeronave] #[tags relevantes]""",

    "es_long": """\
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

#DCSWorld #[Aeronave] #[tags relevantes]""",
}


def _build_description_rules(is_squadron: bool, category: str, config: dict | None = None) -> str:
    """Return length-adapted description template for the Gemini prompt.

    Returns a non-empty custom override from config if present, otherwise the hardcoded default.
    """
    key = f"{'es' if is_squadron else 'en'}_{category}"
    if config:
        custom = config.get("description_templates", {}).get(key, "")
        if custom:
            return custom
    return _DESCRIPTION_TEMPLATES[key]


def _build_module_guide() -> str:
    """Format MODULE_PROFILES as a text block for injection into the Gemini prompt."""
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
                 duration_seconds: float | None = None, series_context: dict | None = None,
                 aircraft_suggestions: list | None = None,
                 audio_markers: list[str] | None = None,
                 acmi_events: dict | None = None) -> str:
    """Build the full Gemini prompt, injecting memory, length rules, series context, and the module guide."""
    recent = memory["videos"][-5:] if memory["videos"] else []
    memory_block = ""
    if recent:
        memory_block = "\n\nRECENT VIDEOS (for style consistency):\n"
        for v in recent:
            memory_block += f"- [{v['date']}] {v['title']} ({v['language']})\n"

    series_block = ""
    if series_context:
        series_block = "\n\nSERIES CONTEXT — this video is part of a campaign:\n"
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

    description_rules = _build_description_rules(is_squadron, category, config)
    # Substitute [link] tokens with actual URLs so Gemini never has to guess them.
    links = config.get("default_links", {}) if config else {}
    description_rules = (description_rules
        .replace("Twitter: [link]", f"Twitter: {links.get('twitter', '')}")
        .replace("Twitch: [link]", f"Twitch: {links.get('twitch', '')}")
        .replace("Buy Me a Coffee: [link]", f"Buy Me a Coffee: {links.get('buymeacoffee', '')}"))

    chapters_rule = {
        "short":  "Do NOT include chapters — video is too short (<10 min). Return empty array [].",
        "medium": "Include chapters only if you can reasonably infer time progression from the frames. If uncertain, return [].",
        "long":   "ALWAYS include chapters — mandatory for long videos. Generate chapters even with rough time estimates.",
    }[category]

    audio_block = ""
    if audio_markers and len(audio_markers) > 1:
        timestamps = ", ".join(audio_markers)
        audio_block = (
            f"- AUDIO PHASE MARKERS detected from silence analysis: {timestamps}\n"
            "  These mark DCS mission phase transitions (briefing → taxi → ingress → combat → RTB).\n"
            "  Use these as your preferred chapter start times and label each one based on context."
        )

    acmi_block = ""
    if acmi_events and acmi_events.get("events_text"):
        acmi_block = (
            f"\nTACVIEW ACMI DATA: {acmi_events['events_text']}\n"
            "Use these confirmed events to improve chapter accuracy and description specificity."
        )

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
{audio_block}{acmi_block}
"""

# ── Gemini API call ───────────────────────────────────────────────────────────

def call_gemini(frames_b64: list[str], prompt: str, model: str) -> str:
    """Call Gemini Vision API using only stdlib (no SDK needed).

    DCS_SIMULATE=1 skips the HTTP call and returns canned metadata (FEA-04):
    lets agents/QA validate the full UI flow without spending Gemini quota.
    """
    if os.environ.get("DCS_SIMULATE") == "1":
        return json.dumps({
            "title": "[SIMULATED] DCS World Sample Flight",
            "description": "Simulated description — DCS_SIMULATE mode, no Gemini call made.",
            "tags": ["dcs", "dcs world", "simulated"],
            "chapters": [],
            "language": "en",
            "aircraft": "",
            "map": "",
            "mission_type": "",
            "campaign": "",
            "analysis_notes": "Simulated metadata — DCS_SIMULATE mode.",
        })

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise OSError("GEMINI_API_KEY not set.")

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
            "maxOutputTokens": 16384
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
                      frames: list | None = None, acmi_path: Path | None = None) -> dict:
    """Analyse a video and return YouTube metadata via Gemini.

    Pass `frames` to skip re-extraction; pass `acmi_path` to inject TacView event context.
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
    except _DURATION_ERRORS:
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

    # Audio chapter detection — only for medium/long videos
    audio_markers = None
    if duration_seconds and duration_seconds >= 600:
        print("  Detecting audio phase markers...")
        markers = detect_audio_chapters(video_path, duration_seconds)
        if len(markers) > 1:
            print(f"  ✓ Audio markers: {', '.join(markers)}")
            audio_markers = markers
        else:
            print("  → No phase transitions detected in audio")

    acmi_events = None
    if acmi_path and acmi_path.exists():
        print("  Parsing TacView ACMI file...")
        acmi_events = parse_acmi_events(acmi_path)
        if acmi_events.get("events_text"):
            print(f"  ✓ ACMI events: {acmi_events['events_text']}")
        else:
            print("  → No significant ACMI events detected")

    model = config.get("model", "gemini-1.5-flash")
    prompt = build_prompt(user_context, config, is_squadron, memory, duration_seconds,
                          series_context, aircraft_suggestions, audio_markers, acmi_events)
    print(f"  Calling Gemini API ({model})...")

    try:
        raw = call_gemini(frames, prompt, model)
    except _GEMINI_ERRORS as e:
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
        if duration_seconds is not None:
            metadata["duration_s"] = duration_seconds
        return metadata
    except json.JSONDecodeError as e:
        # Try to recover truncated JSON by closing open braces/brackets
        print("  ⚠ JSON truncated, attempting recovery...")
        recovered = _recover_json(raw)
        if recovered:
            print("  ✓ Recovered from truncated response")
            if duration_seconds is not None:
                recovered["duration_s"] = duration_seconds
            return recovered
        print(f"  ✗ JSON parse error: {e}")
        print(f"  Raw (first 500 chars): {raw[:500]}")
        return {}


def build_fallback_metadata(video_path: Path, user_context: str, config: dict) -> dict:
    """Build minimal usable metadata when Gemini analysis fails (quota, timeout, bad key).

    Derives the title from the filename and user_context. Uses the generic English medium
    description template. Returns a dict compatible with the normal metadata structure.
    """
    stem = video_path.stem.replace("_", " ").replace("-", " ").strip()
    aircraft = ""
    for module, profile in MODULE_PROFILES.items():
        for tag in profile["tags"]:
            if tag.lower() in (user_context + " " + stem).lower():
                aircraft = module
                break
        if aircraft:
            break

    title_parts = ["DCS World"]
    if aircraft:
        title_parts.append(aircraft)
    if user_context.strip():
        title_parts.append(user_context.strip()[:40])
    elif stem:
        title_parts.append(stem[:40])
    title = " | ".join(title_parts)[:100]

    desc_template = _DESCRIPTION_TEMPLATES.get("en_medium", "")
    links = config.get("default_links", {})
    description = (desc_template
        .replace("Twitter: [link]", f"Twitter: {links.get('twitter', '')}")
        .replace("Twitch: [link]", f"Twitch: {links.get('twitch', '')}")
        .replace("Buy Me a Coffee: [link]", f"Buy Me a Coffee: {links.get('buymeacoffee', '')}"))

    tags = ["dcs", "dcs world", "eagle dynamics", "digital combat simulator",
            "flight simulator", "thecylonpilot", "cylon pilot"]
    if aircraft:
        profile = MODULE_PROFILES.get(aircraft, {})
        tags.extend(profile.get("tags", []))

    try:
        duration_s = _get_video_duration(video_path)
    except _DURATION_ERRORS:
        duration_s = None

    result = {
        "title": title,
        "description": description,
        "tags": tags,
        "chapters": [],
        "language": "en",
        "aircraft": aircraft,
        "map": "",
        "mission_type": "",
        "campaign": "",
        "analysis_notes": "Fallback metadata — Gemini analysis failed.",
    }
    if duration_s is not None:
        result["duration_s"] = duration_s
    return result


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
        elif ch in ('}', ']') and stack:
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

# ── ACMI / Thumbnail generation ────────────────────────────────────────────────
# Extracted to acmi.py (TEC-01a) and thumbnail.py (TEC-01b); reexported here so
# existing dcs_meta.X call sites keep working unchanged.
from acmi import _parse_acmi_props, parse_acmi_events  # noqa: F401
from thumbnail import generate_thumbnail_on_demand  # noqa: F401

# ── Narration script ─────────────────────────────────────────────────────────

def generate_narration_script(metadata: dict, video_path: Path, config: dict) -> str:
    """Generate a 200-300 word voiceover narration script via Gemini.

    Uses a narration-focused prompt with the existing metadata and a small set of
    representative frames. Falls back to a minimal template if the API call fails.
    """
    frames = extract_frames(video_path, min(4, config.get("frames_to_extract", 8)))
    aircraft = metadata.get("aircraft", "your aircraft")
    map_name = metadata.get("map", "the map")
    mission_type = metadata.get("mission_type", "this mission")
    description = metadata.get("description", "")[:600]

    prompt = (
        "You are writing a natural, engaging YouTube voiceover script for a DCS World gameplay video.\n\n"
        f"MISSION CONTEXT:\n"
        f"- Aircraft: {aircraft}\n"
        f"- Map: {map_name}\n"
        f"- Mission type: {mission_type}\n"
        f"- Description excerpt: {description}\n\n"
        "Write a 200-300 word voiceover script in English, first person, natural spoken language.\n"
        "Include key events visible in the frames. Do not use bullet points — write flowing prose.\n"
        "Begin directly with the script text. No preamble, no stage directions, no markdown.\n"
    )

    model = config.get("model", DEFAULT_CONFIG["model"])
    try:
        return call_gemini(frames, prompt, model).strip()
    except _GEMINI_ERRORS:
        return (
            f"Today we're flying the {aircraft} over {map_name}. "
            f"This is a {mission_type} mission. "
            "Let's see how it unfolds."
        )


# ── Duplicate detection ───────────────────────────────────────────────────────

def check_duplicate(metadata: dict, history: dict) -> dict:
    """Compare metadata against history to detect near-duplicate missions.

    Compares aircraft, map, and mission_type fields. Returns a dict with
    is_duplicate (bool), similarity (0.0-1.0), matching_title (str|None),
    and diff (human-readable difference summary).
    """
    aircraft = metadata.get("aircraft", "").lower().strip()
    map_name = metadata.get("map", "").lower().strip()
    mission_type = metadata.get("mission_type", "").lower().strip()

    best_score = 0.0
    best_match = None

    for v in history.get("videos", []):
        score = 0.0
        checks = 0

        if aircraft:
            checks += 1
            if aircraft in v.get("aircraft", "").lower():
                score += 1.0
        if map_name:
            checks += 1
            if map_name in v.get("map", "").lower():
                score += 1.0
        if mission_type:
            checks += 1
            if mission_type in v.get("mission_type", "").lower():
                score += 1.0

        similarity = score / checks if checks else 0.0
        if similarity > best_score:
            best_score = similarity
            best_match = v

    is_dup = best_score >= 0.85

    diff_parts = []
    if best_match:
        if metadata.get("aircraft", "").lower() != best_match.get("aircraft", "").lower():
            diff_parts.append(f"different aircraft ({metadata.get('aircraft')} vs {best_match.get('aircraft')})")
        if metadata.get("map", "").lower() != best_match.get("map", "").lower():
            diff_parts.append(f"different map ({metadata.get('map')} vs {best_match.get('map')})")
        if metadata.get("mission_type", "").lower() != best_match.get("mission_type", "").lower():
            diff_parts.append(f"different mission type ({metadata.get('mission_type')} vs {best_match.get('mission_type')})")

    diff = " | ".join(diff_parts) if diff_parts else "same aircraft, map, and mission type"

    return {
        "is_duplicate": is_dup,
        "similarity": round(best_score, 2),
        "matching_title": best_match.get("title") if best_match else None,
        "diff": diff,
    }


# ── OBS scene metadata ────────────────────────────────────────────────────────

def extract_obs_metadata(video_path: Path) -> dict:
    """Extract OBS scene metadata from MKV file tags using ffprobe.

    Reads the DESCRIPTION tag (if an OBS script wrote scene names) and
    CHAPTER markers. Returns a dict with obs_description (str) and
    chapters (list of {time, title} dicts). Returns empty values if not found.
    """
    result = {"obs_description": "", "chapters": []}
    try:
        import subprocess as _sp
        proc = _sp.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_chapters", str(video_path)],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            return result
        data = json.loads(proc.stdout)
    except (OSError, _sp.TimeoutExpired, json.JSONDecodeError):
        return result

    fmt_tags = data.get("format", {}).get("tags", {})
    obs_desc = fmt_tags.get("DESCRIPTION") or fmt_tags.get("description") or ""
    result["obs_description"] = obs_desc

    for ch in data.get("chapters", []):
        start_s = float(ch.get("start_time", 0))
        title = (ch.get("tags", {}).get("title") or
                 ch.get("tags", {}).get("TITLE") or "")
        result["chapters"].append({
            "time": _seconds_to_chapter_time(start_s),
            "title": title,
            "start_s": start_s,
        })

    return result


# ── Debrief ───────────────────────────────────────────────────────────────────

_DEBRIEF_RESULT_ICON = {"RTB": "✓ RTB", "CRASH": "✗ CRASH", "EJECT": "✗ EJECT", "COMPLETE": "✓ COMPLETE"}


def _format_debrief_duration(seconds: float) -> str:
    """Format seconds as HH:MM:SS (or MM:SS for videos under an hour)."""
    h, r = divmod(int(seconds), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def generate_debrief(metadata: dict, video_path: Path, config: dict,
                     acmi_events: dict | None = None) -> str:
    """Generate a military-format mission debrief report via Gemini frame analysis.

    Pass acmi_events (from parse_acmi_events) for more accurate kill/SAM counts.
    Falls back to metadata-only fields if the API call fails.
    """
    language = metadata.get("language", "en")
    aircraft = metadata.get("aircraft", "?")
    map_name = metadata.get("map", "?")
    mission_type = metadata.get("mission_type", "?")

    duration_str = "--"
    try:
        duration_str = _format_debrief_duration(_get_video_duration(video_path))
    except _DURATION_ERRORS:
        pass

    frames = extract_frames(video_path, min(5, config.get("frames_to_extract", 8)))

    lang_label = "Spanish (Spain)" if language == "es" else "English"
    acmi_hint = ""
    if acmi_events and acmi_events.get("events_text"):
        acmi_hint = (
            f"\n\nTACVIEW ACMI CONFIRMED DATA: {acmi_events['events_text']}. "
            "Use these confirmed counts for kills and SAM fields in your JSON output."
        )
    prompt = (
        "You are generating a mission debrief for a DCS World recording.\n\n"
        f"MISSION INFO: aircraft={aircraft}, map={map_name}, mission_type={mission_type}, "
        f"narrative language={lang_label}"
        + acmi_hint + "\n\n"
        "Analyze the video frames. Estimate from HUD data, RWR activity, and visual cues.\n\n"
        "result values: RTB=landed safely at any base; CRASH=aircraft destroyed, no ejection detected; "
        "EJECT=pilot ejected after aircraft loss (aircraft destroyed but pilot survived by ejecting); "
        "COMPLETE=scenario/campaign objective met.\n\n"
        "Return ONLY a valid JSON object with these exact keys (use null if truly unknown):\n"
        '{\n'
        '  "result": "RTB" | "CRASH" | "EJECT" | "COMPLETE",\n'
        '  "kills": <integer or null>,\n'
        '  "sam_evasions": <integer or null>,\n'
        '  "max_mach": "<e.g. 0.95 or -->",\n'
        '  "max_altitude": "<e.g. 24000 ft or FL240 or -->",\n'
        '  "fuel_remaining": "<e.g. 3200 lb or 45% or -->",\n'
        f'  "narrative": "<2-3 sentences in {lang_label} for the squadron forum>"\n'
        '}\n\n'
        "No markdown fences, no explanation — just the JSON."
    )

    model = config.get("model", DEFAULT_CONFIG["model"])
    data: dict = {}
    try:
        raw = call_gemini(frames, prompt, model).strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        data = json.loads(raw)
    except _GEMINI_ERRORS:
        data = {}

    result_raw = data.get("result", "")
    result_str = _DEBRIEF_RESULT_ICON.get(result_raw, result_raw or "--")
    kills = data.get("kills")
    kills_str = str(kills) if kills is not None else "--"
    sam = data.get("sam_evasions")
    sam_str = str(sam) if sam is not None else "--"

    # ACMI data overrides Gemini frame estimates for confirmed counts
    if acmi_events:
        acmi_kills = acmi_events.get("kills", [])
        if acmi_kills:
            kills_str = str(len(acmi_kills))
        acmi_sams = acmi_events.get("sam_launches", [])
        if acmi_sams:
            sam_str = str(len(acmi_sams))
        # ACMI-confirmed loss/ejection always overrides Gemini's frame-based guess.
        # Ejection takes priority: aircraft was destroyed AND pilot survived by ejecting.
        if acmi_events.get("ejection_events"):
            result_raw = "EJECT"
            result_str = _DEBRIEF_RESULT_ICON["EJECT"]
        elif acmi_events.get("friendly_losses"):
            result_raw = "CRASH"
            result_str = _DEBRIEF_RESULT_ICON["CRASH"]

    sep = "━" * 44
    narrative = (data.get("narrative") or "").strip()

    if language == "es":
        lines = [
            sep,
            "  DEBRIEF — ESCUADRÓN 111",
            sep,
            "",
            f"  Aeronave:          {aircraft}",
            f"  Mapa:              {map_name}",
            f"  Tipo de misión:    {mission_type}",
            f"  Duración:          {duration_str}",
            "",
            f"  Resultado:         {result_str}",
            f"  Bajas enemigas:    {kills_str}",
            f"  Evasiones SAM:     {sam_str}",
            f"  Mach máximo:       {data.get('max_mach', '--')}",
            f"  Altitud máxima:    {data.get('max_altitude', '--')}",
            f"  Combustible:       {data.get('fuel_remaining', '--')}",
        ]
    else:
        lines = [
            sep,
            "  MISSION DEBRIEF",
            sep,
            "",
            f"  Aircraft:          {aircraft}",
            f"  Map:               {map_name}",
            f"  Mission type:      {mission_type}",
            f"  Duration:          {duration_str}",
            "",
            f"  Result:            {result_str}",
            f"  Enemy kills:       {kills_str}",
            f"  SAM evasions:      {sam_str}",
            f"  Max Mach:          {data.get('max_mach', '--')}",
            f"  Max altitude:      {data.get('max_altitude', '--')}",
            f"  Fuel remaining:    {data.get('fuel_remaining', '--')}",
        ]

    if narrative:
        lines += ["", sep, f"  {narrative}", sep]
    else:
        lines.append(sep)

    return "\n".join(lines)


# ── Social media captions ────────────────────────────────────────────────────

def generate_social_captions(metadata: dict, config: dict) -> dict:
    """Generate platform-adapted social media captions from metadata via Gemini.

    Returns a dict with keys twitter, instagram, linkedin, tiktok. Each value
    is a platform-appropriate caption string with hashtags. Falls back to
    simple templates if the Gemini call fails.
    """
    title = metadata.get("title", "DCS World video")
    aircraft = metadata.get("aircraft", "")
    map_name = metadata.get("map", "")
    mission_type = metadata.get("mission_type", "")
    description = metadata.get("description", "")[:300]
    hashtags_base = " ".join(f"#{t.replace(' ', '')}" for t in ["DCSWorld", "FlightSim", aircraft.replace("/", "").replace("-", "").replace(" ", "")] if t)

    prompt = (
        "Generate social media captions for this DCS World gameplay video. "
        "Return ONLY a valid JSON object with keys: twitter, instagram, linkedin, tiktok.\n\n"
        f"VIDEO TITLE: {title}\n"
        f"AIRCRAFT: {aircraft}\n"
        f"MAP: {map_name}\n"
        f"MISSION TYPE: {mission_type}\n"
        f"DESCRIPTION EXCERPT: {description}\n\n"
        "REQUIREMENTS:\n"
        "- twitter: max 280 chars, punchy, 3-5 hashtags at end\n"
        "- instagram: engaging with CTA, 8-10 hashtags on new lines after caption\n"
        "- linkedin: professional/educational tone, 2-3 hashtags max, no spam\n"
        "- tiktok: energetic, 15-20 hashtags, trending format\n\n"
        "Return raw JSON only. No markdown fences."
    )

    model = config.get("model", DEFAULT_CONFIG["model"])
    try:
        raw = call_gemini([], prompt, model).strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        result = json.loads(raw)
        return {
            "twitter": result.get("twitter", ""),
            "instagram": result.get("instagram", ""),
            "linkedin": result.get("linkedin", ""),
            "tiktok": result.get("tiktok", ""),
        }
    except _GEMINI_ERRORS:
        fallback = f"{title} {hashtags_base}"
        return {
            "twitter": fallback[:280],
            "instagram": fallback,
            "linkedin": f"New DCS World video: {title}",
            "tiktok": fallback,
        }


# ── Pre-upload checklist ──────────────────────────────────────────────────────

def run_upload_checklist(metadata: dict, config: dict) -> list[dict]:
    """Validate metadata before upload and return a checklist of rule results.

    Returns a list of dicts with keys: rule (str), status ('ok'|'warn'|'fail'), message (str).
    """
    title = metadata.get("title", "")
    description = metadata.get("description", "")
    tags = metadata.get("tags", [])
    aircraft = metadata.get("aircraft", "")

    checks = []

    title_len = len(title)
    if 50 <= title_len <= 70:
        checks.append({"rule": "Title length", "status": "ok", "message": f"{title_len} chars (50-70 recommended)"})
    else:
        checks.append({"rule": "Title length", "status": "warn",
                       "message": f"{title_len} chars — optimal range is 50-70 chars"})

    desc_len = len(description)
    if desc_len >= 300:
        checks.append({"rule": "Description length", "status": "ok", "message": f"{desc_len} chars"})
    else:
        checks.append({"rule": "Description length", "status": "fail",
                       "message": f"{desc_len} chars — minimum 300 recommended"})

    tag_count = len(tags)
    if 7 <= tag_count <= 15:
        checks.append({"rule": "Tag count", "status": "ok", "message": f"{tag_count} tags (7-15 recommended)"})
    else:
        checks.append({"rule": "Tag count", "status": "warn",
                       "message": f"{tag_count} tags — optimal range is 7-15"})

    has_dcs = "dcs world" in title.lower() or "dcs world" in description.lower()
    checks.append({
        "rule": '"DCS World" present',
        "status": "ok" if has_dcs else "fail",
        "message": "Found in title/description" if has_dcs else '"DCS World" missing from title and description',
    })

    if aircraft:
        has_aircraft = aircraft.lower() in title.lower() or aircraft.lower() in description.lower()
        checks.append({
            "rule": "Aircraft name present",
            "status": "ok" if has_aircraft else "warn",
            "message": f"{aircraft} found" if has_aircraft else f"{aircraft} missing from title/description",
        })

    return checks


# ── SEO ───────────────────────────────────────────────────────────────────────

def check_description_seo(
    description: str,
    title: str,
    tags: list,
    aircraft: str,
    mission_type: str,
    chapters: list,
    config: dict,
) -> list[dict]:
    """Validate description SEO and return a list of issue dicts (code, severity, message, suggestion)."""
    issues = []
    desc_lower = description.lower()
    title_lower = title.lower()

    if len(description) < 300:
        issues.append({
            "code": "SHORT_DESCRIPTION",
            "severity": "warning",
            "message": f"Description is {len(description)} chars — recommended minimum is 300",
            "suggestion": "Expand with more mission context, aircraft systems used, or tactical details.",
        })

    if "dcs world" not in desc_lower and "dcs world" not in title_lower:
        issues.append({
            "code": "MISSING_DCS_WORLD",
            "severity": "warning",
            "message": '"DCS World" not found in title or description',
            "suggestion": 'Add "DCS World" near the beginning of the description.',
        })

    if aircraft and aircraft.lower() not in desc_lower:
        issues.append({
            "code": "MISSING_AIRCRAFT",
            "severity": "warning",
            "message": f'Aircraft "{aircraft}" not mentioned in description',
            "suggestion": f'Include "{aircraft}" for better search indexing.',
        })

    if mission_type and mission_type.lower() not in desc_lower:
        issues.append({
            "code": "MISSING_MISSION_TYPE",
            "severity": "info",
            "message": f'Mission type "{mission_type}" not in description',
            "suggestion": f'Adding "{mission_type}" helps viewers find specific content.',
        })

    if chapters:
        timestamp_match = re.search(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', description)
        if not timestamp_match:
            issues.append({
                "code": "NO_CHAPTERS_IN_DESC",
                "severity": "warning",
                "message": "Chapters detected but no timestamps found in description",
                "suggestion": "Add the chapter timestamps to the description body.",
            })
        elif timestamp_match.start() > 500:
            issues.append({
                "code": "CHAPTERS_TOO_LATE",
                "severity": "info",
                "message": f"First chapter timestamp at char {timestamp_match.start()} — recommended before char 500",
                "suggestion": "Move the chapters section closer to the top of the description.",
            })

    playlist_links = [v for k, v in config.get("default_links", {}).items() if "playlist" in k]
    has_playlist = any(link in description for link in playlist_links)
    playlist_early = any(link in description[:100] for link in playlist_links)
    if has_playlist and not playlist_early:
        issues.append({
            "code": "PLAYLIST_NOT_EARLY",
            "severity": "info",
            "message": "Playlist link appears after the first 100 chars",
            "suggestion": "Move the most relevant playlist link to the very beginning of the description.",
        })

    return issues


def rewrite_description_seo(
    description: str,
    issues: list,
    aircraft: str,
    mission_type: str,
    language: str,
    config: dict,
) -> str:
    """Send description + SEO issues to Gemini for a targeted rewrite; returns the rewritten description."""
    model = config.get("model", DEFAULT_CONFIG["model"])
    issue_lines = "\n".join(
        f"- [{i['severity'].upper()}] {i['message']}: {i['suggestion']}"
        for i in issues
    )
    prompt = (
        f"You are an expert YouTube SEO specialist for DCS World simulation gaming content.\n\n"
        f"Rewrite the following description to fix the listed SEO issues. "
        f"Preserve all existing URLs, playlist links, chapter timestamps and their order, "
        f"hashtags, and the language ({language}).\n\n"
        f"CURRENT DESCRIPTION:\n{description}\n\n"
        f"SEO ISSUES TO FIX:\n{issue_lines}\n\n"
        f"Return ONLY the rewritten description text. No explanations, no markdown, no code fences."
    )
    return call_gemini([], prompt, model).strip()


# ── Output ────────────────────────────────────────────────────────────────────

def format_description(metadata: dict, config: dict) -> str:
    """Replace playlist placeholder tokens in the description with the configured URLs."""
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
    """Write metadata to timestamped .json and .txt files in the output folder."""
    OUTPUT_PATH.mkdir(exist_ok=True)
    stem = video_path.stem
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 — nombre de fichero en hora local de la máquina, intencional
    base = OUTPUT_PATH / f"{stem}_{timestamp}"

    metadata["description"] = format_description(metadata, config)

    json_path = base.with_suffix(".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    txt_path = base.with_suffix(".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{'═'*60}\n  DCS YouTube Metadata — TheCylonPilot\n")
        f.write(f"  Video: {video_path.name}\n")
        f.write(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'═'*60}\n\n")  # noqa: DTZ005 — hora local de la máquina, intencional
        f.write(f"TITLE\n{'─'*40}\n{metadata.get('title','')}\n\n")
        f.write(f"DESCRIPTION\n{'─'*40}\n{metadata.get('description','')}\n\n")
        f.write(f"TAGS\n{'─'*40}\n{', '.join(metadata.get('tags', []))}\n\n")
        chapters = metadata.get("chapters", [])
        if chapters:
            f.write(f"CHAPTERS\n{'─'*40}\n")
            f.writelines(f"{ch['time']} {ch['label']}\n" for ch in chapters)
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
            "date": datetime.now().strftime("%Y-%m-%d"),  # noqa: DTZ005 — fecha local de la máquina, intencional
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


# ── YouTube Shorts ───────────────────────────────────────────────────────────

_HOOK_MAP = {
    "kill":       "This kill 🔥",
    "ejection":   "Ejection sequence 🪂",
    "guided_bomb": "Precision strike 💣",
    "sam":        "SAM evasion ⚡",
    "bvr":        "BVR engagement 🎯",
    "audio_peak": "Action moment ✈️",
}

_SCORE_MAP = {
    "kill": 10,
    "ejection": 10,
    "guided_bomb": 9,
    "sam": 7,
    "bvr": 6,
    "audio_peak": 5,
}


def _collect_candidate_timestamps(acmi_events: dict) -> list[tuple[float, str, str]]:
    """Extract (timestamp_sec, event_type, event_name) triples from acmi_events."""
    candidates: list[tuple[float, str, str]] = []
    for ev in acmi_events.get("kills", []):
        candidates.append((float(ev.get("time_s", ev.get("timestamp_sec", 0))), "kill", ev.get("name", "unknown")))
    for ev in acmi_events.get("ejection_events", []):
        candidates.append((float(ev.get("time_s", ev.get("timestamp_sec", 0))), "ejection", ev.get("name", "friendly pilot")))
    for ev in acmi_events.get("bomb_releases", []):
        candidates.append((float(ev.get("time_s", ev.get("timestamp_sec", 0))), "guided_bomb", ev.get("name", "guided bomb")))
    for ev in acmi_events.get("sam_launches", []):
        candidates.append((float(ev.get("time_s", ev.get("timestamp_sec", 0))), "sam", ev.get("name", "SAM")))
    for ev in acmi_events.get("bvr_launches", []):
        candidates.append((float(ev.get("time_s", ev.get("timestamp_sec", 0))), "bvr", ev.get("name", "BVR missile")))
    return candidates


def _parse_audio_peaks(stderr: str, threshold_db: float = -20.0) -> list[float]:
    """Parse RMS level lines from ffmpeg astats output and return peak timestamps above threshold."""
    timestamps: list[float] = []
    current_time: float = 0.0
    for line in stderr.splitlines():
        line = line.strip()
        if line.startswith("pts_time:"):
            try:
                current_time = float(line.split(":", 1)[1].strip())
            except (ValueError, IndexError):
                pass
        elif "lavfi.astats.Overall.RMS_level=" in line:
            try:
                val = float(line.split("=", 1)[1].strip())
                if val > threshold_db:
                    timestamps.append(current_time)
            except (ValueError, IndexError):
                pass
    return timestamps


def _deduplicate_candidates(
    candidates: list[tuple[float, str, str]], min_gap_s: float = 30.0
) -> list[tuple[float, str, str]]:
    """Remove candidates within min_gap_s of a higher-priority one (keep higher-score event)."""
    priority_order = ["kill", "ejection", "guided_bomb", "sam", "bvr", "audio_peak"]
    sorted_by_priority = sorted(
        candidates,
        key=lambda x: priority_order.index(x[1]) if x[1] in priority_order else 99,
    )
    kept: list[tuple[float, str, str]] = []
    for ts, evt, name in sorted_by_priority:
        if not any(abs(ts - k[0]) < min_gap_s for k in kept):
            kept.append((ts, evt, name))
    return kept


def detect_short_clips(
    video_path: Path, acmi_events: dict, config: dict, window_minutes: int = 5
) -> list[dict]:
    """Detect action moments using a window-based approach and extract candidate Shorts clips.

    Divides the video into windows of window_minutes each. For each window, selects the
    highest-priority ACMI event, falling back to an audio peak, then the window midpoint.
    Returns one clip per window; no hard cap on total clips.
    """
    import math

    try:
        video_duration = _get_video_duration(video_path)
    except _DURATION_ERRORS:
        video_duration = 0.0

    acmi_candidates = _collect_candidate_timestamps(acmi_events)

    audio_peaks: list[float] = []
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", str(video_path),
                "-af", ("astats=metadata=1:reset=1,"
                        "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-"),
                "-f", "null", "-",
            ],
            capture_output=True, text=True, check=False,
        )
        audio_peaks = _parse_audio_peaks(result.stderr)
    except (FileNotFoundError, OSError):
        pass

    window_sec = window_minutes * 60
    num_windows = max(1, math.ceil(video_duration / window_sec)) if video_duration else 1

    shorts_dir = OUTPUT_PATH / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)

    clips: list[dict] = []
    for i in range(num_windows):
        window_start = i * window_sec
        window_end = min((i + 1) * window_sec, video_duration) if video_duration else (i + 1) * window_sec

        window_acmi = [
            (ts, evt, name)
            for ts, evt, name in acmi_candidates
            if window_start <= ts < window_end
        ]
        if window_acmi:
            ts, evt, event_name = max(window_acmi, key=lambda x: _SCORE_MAP.get(x[1], 0))
        else:
            peaks_in_window = [t for t in audio_peaks if window_start <= t < window_end]
            ts = peaks_in_window[0] if peaks_in_window else (window_start + window_end) / 2
            evt = "audio_peak"
            event_name = "audio_peak"

        start = max(0.0, ts - 15.0)
        duration = min(60.0, video_duration - start) if video_duration else 60.0
        if duration <= 0:
            continue

        output_path = shorts_dir / f"{video_path.stem}_short_{i + 1}.mp4"
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", str(video_path),
                    "-t", str(duration),
                    "-vf", "crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac",
                    str(output_path),
                ],
                capture_output=True, check=True,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue

        clips.append({
            "start_sec": start,
            "duration_sec": duration,
            "clip_path": str(output_path),
            "hook": _HOOK_MAP.get(evt, "Action moment ✈️"),
            "score": _SCORE_MAP.get(evt, 5),
            "event_type": evt,
            "event_name": event_name,
        })

    clips.sort(key=lambda x: x["score"], reverse=True)
    return clips


_EVENT_TITLE_MAP: dict[str, object] = {
    "kill":        lambda n: f"{n} Kill" if n and n not in ("unknown", "") else "Air Kill",
    "ejection":    lambda n: "Ejection Sequence",
    "guided_bomb": lambda n: f"{n} Strike" if n and n not in ("guided bomb", "") else "Precision Strike",
    "sam":         lambda n: f"{n} Evasion" if n and n not in ("SAM", "") else "SAM Evasion",
    "bvr":         lambda n: f"{n} Shot" if n and n not in ("BVR missile", "") else "BVR Shot",
    "audio_peak":  lambda n: "Cockpit Footage",
}

_EVENT_DESC_MAP: dict[str, object] = {
    "kill":        lambda n: f"Air-to-air kill of a {n} in DCS World." if n and n not in ("unknown", "") else "Air-to-air kill in DCS World.",
    "ejection":    lambda n: "Ejection sequence captured during a DCS World mission.",
    "guided_bomb": lambda n: f"Precision strike with a {n} in DCS World." if n and n not in ("guided bomb", "") else "Precision strike in DCS World.",
    "sam":         lambda n: f"SAM evasion — {n} fired at us in DCS World." if n and n not in ("SAM", "") else "SAM evasion in DCS World.",
    "bvr":         lambda n: f"BVR engagement — {n} fired in DCS World." if n and n not in ("BVR missile", "") else "BVR engagement in DCS World.",
    "audio_peak":  lambda n: "Cockpit footage from a DCS World mission.",
}

_EVENT_TAGS_MAP: dict[str, object] = {
    "kill":        lambda n: ["Kill", n] if n and n not in ("unknown", "") else ["Kill"],
    "ejection":    lambda n: ["Ejection"],
    "guided_bomb": lambda n: ["PrecisionStrike", n] if n and n not in ("guided bomb", "") else ["PrecisionStrike"],
    "sam":         lambda n: ["SAMEvasion", n] if n and n not in ("SAM", "") else ["SAMEvasion"],
    "bvr":         lambda n: ["BVR", n] if n and n not in ("BVR missile", "") else ["BVR"],
    "audio_peak":  lambda n: ["Cockpit"],
}


def generate_short_metadata(clip: dict, base_metadata: dict, config: dict) -> dict:
    """Generate YouTube Shorts metadata unique to this clip's event context.

    Uses event_type and event_name from the clip to build a distinct title, description,
    and tag set. Falls back to audio_peak defaults when event context is absent.
    """
    aircraft = base_metadata.get("aircraft", "")
    event_type = clip.get("event_type", "audio_peak")
    event_name = clip.get("event_name", "")

    title_fn = _EVENT_TITLE_MAP.get(event_type, _EVENT_TITLE_MAP["audio_peak"])
    raw_title = f"{title_fn(event_name)} | DCS {aircraft} #Shorts"
    title = raw_title[:100]

    event_desc = _EVENT_DESC_MAP.get(event_type, _EVENT_DESC_MAP["audio_peak"])(event_name)
    base_desc = base_metadata.get("description", "")[:150]
    aircraft_tag = aircraft.replace(" ", "").replace("/", "").replace("-", "")
    description = f"{event_desc}\n\n{base_desc}\n\n#Shorts #DCSWorld #{aircraft_tag}"

    event_tags: list[str] = _EVENT_TAGS_MAP.get(event_type, _EVENT_TAGS_MAP["audio_peak"])(event_name)
    base_tags = base_metadata.get("tags", [])[:10]
    tags = base_tags + event_tags + ["Shorts", "DCSWorld", "YouTube Shorts"]

    return {"title": title, "description": description, "tags": tags}


def print_preview(metadata: dict):
    """Print a terminal preview of the generated metadata (title, description excerpt, tags, chapters)."""
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

    print("\n✓ Done. Check the output/ folder.\n")


if __name__ == "__main__":
    main()
