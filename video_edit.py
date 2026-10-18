"""Automatic video editing (FEA-09): dead-time proposal from the player's ACMI telemetry.

Phase 0 measured that image motion and audio level do not separate dead time in DCS VR recordings,
while the player's own telemetry (gear, speed, height, heading, controls) does. See SPEC.md.
"""

import io
import math
import zipfile
from bisect import bisect_left
from pathlib import Path

import acmi

KT_PER_MS = 1.94384          # el ACMI guarda la velocidad en m/s
DEFAULT_FADE_S = 0.3
PHASES = ("rodaje", "despegue", "navegacion", "aproximacion")
ACTIONS = ("speed", "cut", "keep")
_ESSENTIAL = ("alt", "ias", "agl", "gear")
_MIN_PHASE_S = 15            # segmentos de fase más cortos se absorben en el anterior


# ── Lectura de la telemetría del ACMI ─────────────────────────────────────────

def _acmi_lines(acmi_path: Path):
    acmi_path = Path(acmi_path)
    if zipfile.is_zipfile(acmi_path):
        with zipfile.ZipFile(acmi_path) as zf:
            inner = next((n for n in zf.namelist() if n.lower().endswith(".acmi")), zf.namelist()[0])
            yield from io.TextIOWrapper(zf.open(inner), encoding="utf-8-sig", errors="replace")
    else:
        with open(acmi_path, encoding="utf-8-sig", errors="replace") as f:
            yield from f


def _find_player_id(acmi_path: Path) -> str | None:
    """The player's aircraft is the only object that carries cockpit data (IAS and LandingGear)."""
    for line in _acmi_lines(acmi_path):
        if "IAS=" in line and "LandingGear=" in line and line[0] != "#":
            return line.split(",", 1)[0]
    return None


def read_player_telemetry(acmi_path: Path) -> dict:
    """Return the player's telemetry at 1 Hz in ACMI time (keys t, alt, ias_kt, agl, gear, hdm, roll, pitch).

    Raises ValueError when the ACMI has no aircraft with cockpit data (e.g. a spectator recording).
    """
    pid = _find_player_id(acmi_path)
    if pid is None:
        raise ValueError("No player aircraft with cockpit telemetry found in the ACMI")

    props_map = {"IAS": "ias", "AGL": "agl", "LandingGear": "gear", "HDM": "hdm",
                 "RollControlPosition": "roll", "PitchControlPosition": "pitch"}
    state = {"alt": None, "ias": None, "agl": None, "gear": None, "hdm": 0.0, "roll": 0.0, "pitch": 0.0}
    tel = {k: [] for k in ("t", "alt", "ias_kt", "agl", "gear", "hdm", "roll", "pitch")}
    marker = 0.0
    next_s = None

    def emit_until(limit, inclusive):
        nonlocal next_s
        while next_s is not None and (next_s <= limit if inclusive else next_s < limit):
            tel["t"].append(float(next_s))
            tel["alt"].append(state["alt"])
            tel["ias_kt"].append(state["ias"] * KT_PER_MS)
            for k in ("agl", "gear", "hdm", "roll", "pitch"):
                tel[k].append(state[k])
            next_s += 1

    prefix = pid + ","
    for line in _acmi_lines(acmi_path):
        line = line.rstrip("\r\n")
        if line.startswith("#"):
            try:
                new_marker = float(line[1:])
            except ValueError:
                continue
            emit_until(new_marker, inclusive=False)      # el estado vale hasta que llega el marcador siguiente
            marker = new_marker
        elif line.startswith(prefix):
            props, _flags = acmi._parse_acmi_props(line[len(prefix):])
            for key, value in props.items():
                try:
                    if key == "T":
                        lon_lat_alt = value.split("|")
                        if len(lon_lat_alt) >= 3 and lon_lat_alt[2]:
                            state["alt"] = float(lon_lat_alt[2])
                    elif key in props_map:
                        state[props_map[key]] = float(value)
                except ValueError:
                    continue
            if next_s is None and all(state[k] is not None for k in _ESSENTIAL):
                next_s = math.ceil(marker)
    emit_until(marker, inclusive=True)
    if not tel["t"]:
        raise ValueError("No player aircraft with cockpit telemetry found in the ACMI")
    return tel


# ── Fases de vuelo y tramos estáticos ─────────────────────────────────────────

def _absorb_short_runs(labels: list, min_len: int) -> list:
    runs = []
    for i, label in enumerate(labels):
        if runs and runs[-1][0] == label:
            runs[-1][2] = i
        else:
            runs.append([label, i, i])
    out = list(labels)
    for k, (_, a, b) in enumerate(runs):
        if k and b - a + 1 < min_len:
            out[a:b + 1] = [runs[k - 1][0]] * (b - a + 1)
    return out


def classify_phases(tel: dict) -> list:
    """Label each second: rodaje, despegue, navegacion or aproximacion (landing included)."""
    raw = []
    seen_ground = False
    for gear, ias, agl in zip(tel["gear"], tel["ias_kt"], tel["agl"]):
        if gear >= 0.5 and ias < 60 and agl < 30:
            seen_ground = True
            raw.append("rodaje")
        elif gear >= 0.5:
            recent_ground = "rodaje" in raw[-180:]
            raw.append("despegue" if seen_ground and agl < 600 and recent_ground else "aproximacion")
        else:
            seen_ground = False
            raw.append("navegacion")
    return _absorb_short_runs(raw, _MIN_PHASE_S)


def steady_flags(tel: dict, win: int = 60) -> list:
    """True for seconds inside a window where altitude, speed, heading and controls do not change."""
    n = len(tel["t"])
    stick = [0.0] + [max(abs(tel["roll"][i] - tel["roll"][i - 1]), abs(tel["pitch"][i] - tel["pitch"][i - 1]))
                     for i in range(1, n)]
    flags = [False] * n
    for a in range(0, n - win, 5):
        b = a + win
        heading_change = max(abs(((tel["hdm"][j] - tel["hdm"][a] + 180) % 360) - 180) for j in range(a, b, 5))
        steady = (max(tel["alt"][a:b]) - min(tel["alt"][a:b]) < 100
                  and max(tel["ias_kt"][a:b]) - min(tel["ias_kt"][a:b]) < 15
                  and heading_change < 10 and sum(stick[a:b]) / win < 0.01)
        if steady:
            flags[a:b] = [True] * win
    return flags


# ── Propuesta de tramos muertos ───────────────────────────────────────────────

def propose_segments(tel: dict, event_times: list, offset_s: float, video_duration: float | None,
                     min_run_s: int = 60, margin_s: int = 10, min_kept_s: int = 40,
                     event_guard_s: int = 20) -> list:
    """Dead-time segments in video time: ground idling or steady cruise, away from combat events.

    event_times are in video time (parse_acmi_events with the same offset). Each segment is trimmed
    by margin_s on both sides to protect the transitions, then shifted to video time and clamped.
    """
    phases = classify_phases(tel)
    steady = steady_flags(tel)
    events = sorted(event_times)
    t = tel["t"]

    def near_event(video_t):
        i = bisect_left(events, video_t)
        return any(abs(events[j] - video_t) < event_guard_s for j in (i - 1, i) if 0 <= j < len(events))

    dead = [(phases[i] == "rodaje" or (steady[i] and phases[i] == "navegacion"))
            and not near_event(t[i] - offset_s) for i in range(len(t))]

    segments, start = [], None
    for i, flag in enumerate(dead + [False]):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            seg = _trim_run(t, phases[start:i], start, i - 1, offset_s, video_duration,
                            min_run_s, margin_s, min_kept_s)
            if seg:
                segments.append(seg)
            start = None
    return segments


def _trim_run(t, run_phases, a, b, offset_s, video_duration, min_run_s, margin_s, min_kept_s):
    if b - a + 1 < min_run_s:
        return None
    start, end = t[a] + margin_s - offset_s, t[b] - margin_s - offset_s
    start = max(start, 0.0)
    if video_duration is not None:
        end = min(end, video_duration)
    if end - start < min_kept_s:
        return None
    phase = max(set(run_phases), key=run_phases.count)
    return {"start": start, "end": end, "fase": phase,
            "reason": "rodaje" if phase == "rodaje" else "navegacion estatica", "action": "speed"}


# ── Velocidad y resumen del plan ──────────────────────────────────────────────

def speed_plan(length_s: float, speed: float | None = None, target_s: float = 20.0,
               lo: float = 4.0, hi: float = 16.0) -> dict:
    """How a segment is sped up: ~target_s of output between lo and hi times, cutting what hi cannot absorb.

    A manual `speed` overrides the rule and never cuts.
    """
    if speed:
        factor, accelerated = float(speed), length_s
    else:
        factor = min(hi, max(lo, length_s / target_s))
        accelerated = min(length_s, target_s * factor)
    return {"factor": factor, "accelerated_s": accelerated, "cut_s": length_s - accelerated,
            "out_s": accelerated / factor}


def _validate_segments(segments: list, video_duration: float) -> list:
    ordered = sorted(segments, key=lambda s: s.get("start", 0))
    previous_end = 0.0
    for seg in ordered:
        if seg.get("action") not in ACTIONS:
            raise ValueError(f"invalid action {seg.get('action')!r}")
        start, end = seg.get("start"), seg.get("end")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or not start < end:
            raise ValueError("segment start must be before its end")
        if start < 0 or end > video_duration:
            raise ValueError("segment is outside the video")
        if start < previous_end:
            raise ValueError("segments overlap")
        previous_end = end
        speed = seg.get("speed")
        if speed is not None and not (isinstance(speed, (int, float)) and 1 < speed <= 64):
            raise ValueError("speed must be a number between 1 and 64")
    return ordered


def summarize_plan(segments: list, video_duration: float, fade_s: float = DEFAULT_FADE_S) -> dict:
    """Per-segment speed/output length and the resulting video duration (fades overlap the joins)."""
    ordered = _validate_segments(segments, video_duration)
    out_segments, pieces, cursor = [], [], 0.0

    def add_normal(length):
        if length <= 0:
            return
        if pieces and pieces[-1][0] == "n":
            pieces[-1][1] += length
        else:
            pieces.append(["n", length])

    for seg in ordered:
        add_normal(seg["start"] - cursor)
        length = seg["end"] - seg["start"]
        if seg["action"] == "speed":
            plan = speed_plan(length, seg.get("speed"))
            pieces.append(["a", plan["out_s"]])
            out_segments.append({**seg, **plan})
        elif seg["action"] == "cut":
            pieces.append(["c", 0.0])
            out_segments.append({**seg, "factor": None, "accelerated_s": 0.0, "cut_s": length, "out_s": 0.0})
        else:
            add_normal(length)
            out_segments.append({**seg, "factor": 1.0, "accelerated_s": 0.0, "cut_s": 0.0, "out_s": length})
        cursor = seg["end"]
    add_normal(video_duration - cursor)

    kept = [p for p in pieces if p[0] != "c"]
    resulting = sum(p[1] for p in kept) - fade_s * max(0, len(kept) - 1)
    return {"segments": out_segments, "original_duration": video_duration, "resulting_duration": resulting,
            "fade_s": fade_s}


# ── Orquestador ───────────────────────────────────────────────────────────────

def analyze_cuts(video_path: Path, acmi_path: Path, offset_s: float | None = None) -> dict:
    """Propose dead-time segments for a recording and summarise the resulting edit."""
    # Deferred import: dcs_meta is the larger module and imports acmi (TEC-01c)
    from dcs_meta import _get_video_duration

    duration = _get_video_duration(Path(video_path))
    offset = acmi.resolve_acmi_offset(Path(video_path), Path(acmi_path), offset_s)
    events = acmi.parse_acmi_events(Path(acmi_path), offset_s=offset)
    event_times = [e["time_s"] for key in ("kills", "sam_launches", "bvr_launches", "ir_launches",
                                           "bomb_releases", "ejection_events") for e in events.get(key, [])]
    tel = read_player_telemetry(acmi_path)
    segments = propose_segments(tel, event_times, offset, duration)
    return {**summarize_plan(segments, duration), "offset_s": offset}
