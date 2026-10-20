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
                     event_guard_s: int = 20, landing_guard_s: int = 45) -> list:
    """Dead-time segments in video time: ground idling or steady cruise, away from combat events.

    event_times are in video time (parse_acmi_events with the same offset). Each segment is trimmed
    by margin_s on both sides to protect the transitions, then shifted to video time and clamped.
    A ground run that follows an approach (touchdown) starts landing_guard_s late, so the rollout
    plays at normal speed: rodaje starts below 60 kt, well before the aircraft is actually taxiing.
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
            after_touchdown = start > 0 and phases[start - 1] == "aproximacion"
            seg = _trim_run(t, phases[start:i], start, i - 1, offset_s, video_duration,
                            min_run_s, landing_guard_s if after_touchdown else margin_s, margin_s, min_kept_s)
            if seg:
                segments.append(seg)
            start = None
    return segments


def _trim_run(t, run_phases, a, b, offset_s, video_duration, min_run_s, start_margin_s, margin_s, min_kept_s):
    if b - a + 1 < min_run_s:
        return None
    start, end = t[a] + start_margin_s - offset_s, t[b] - margin_s - offset_s
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


def build_pieces(segments: list, video_duration: float) -> list:
    """Ordered output pieces of an edit: {"kind": normal|speed|cut, start, end, out_s, ...} in source seconds.

    Normal footage between segments and `keep` segments merge into one normal piece; a `cut` leaves a marker
    so the footage on both sides is joined with a fade instead of being merged. A sped-up segment only covers
    the part speed_plan() accelerates (the rest is cut).
    """
    ordered = _validate_segments(segments, video_duration)
    pieces, cursor = [], 0.0

    def add_normal(start, end):
        if end - start <= 0:
            return
        if pieces and pieces[-1]["kind"] == "normal" and pieces[-1]["end"] == start:
            pieces[-1]["end"] = end
            pieces[-1]["out_s"] = end - pieces[-1]["start"]
        else:
            pieces.append({"kind": "normal", "start": start, "end": end, "out_s": end - start})

    for seg in ordered:
        add_normal(cursor, seg["start"])
        length = seg["end"] - seg["start"]
        if seg["action"] == "speed":
            plan = speed_plan(length, seg.get("speed"))
            pieces.append({"kind": "speed", "start": seg["start"], "end": seg["start"] + plan["accelerated_s"],
                           "out_s": plan["out_s"], "factor": plan["factor"], "fase": seg.get("fase")})
        elif seg["action"] == "cut":
            pieces.append({"kind": "cut", "start": seg["start"], "end": seg["end"], "out_s": 0.0})
        else:
            add_normal(seg["start"], seg["end"])
        cursor = seg["end"]
    add_normal(cursor, video_duration)
    return pieces


def kept_pieces(pieces: list) -> list:
    return [p for p in pieces if p["kind"] != "cut"]


def summarize_plan(segments: list, video_duration: float, fade_s: float = DEFAULT_FADE_S) -> dict:
    """Per-segment speed/output length and the resulting video duration (fades overlap the joins)."""
    ordered = _validate_segments(segments, video_duration)
    out_segments = []
    for seg in ordered:
        length = seg["end"] - seg["start"]
        if seg["action"] == "speed":
            out_segments.append({**seg, **speed_plan(length, seg.get("speed"))})
        elif seg["action"] == "cut":
            out_segments.append({**seg, "factor": None, "accelerated_s": 0.0, "cut_s": length, "out_s": 0.0})
        else:
            out_segments.append({**seg, "factor": 1.0, "accelerated_s": 0.0, "cut_s": 0.0, "out_s": length})
    kept = kept_pieces(build_pieces(segments, video_duration))
    resulting = sum(p["out_s"] for p in kept) - fade_s * max(0, len(kept) - 1)
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


# ── Highlights (fase 2) ───────────────────────────────────────────────────────

# Prioridad de mayor a menor (el orden de _deduplicate_candidates) y su clave en parse_acmi_events.
HIGHLIGHT_TYPES = ("kill", "ejection", "guided_bomb", "sam", "bvr")
_EVENT_KEYS = {"kill": "kills", "ejection": "ejection_events", "guided_bomb": "bomb_releases",
               "sam": "sam_launches", "bvr": "bvr_launches"}
DEFAULT_WINDOWS = {"kill": {"before_s": 20, "after_s": 10}, "ejection": {"before_s": 15, "after_s": 10},
                   "guided_bomb": {"before_s": 20, "after_s": 15}, "sam": {"before_s": 15, "after_s": 10},
                   "bvr": {"before_s": 20, "after_s": 15}}
MAX_WINDOW_S = 120
_FILL_TAKEOFF_S, _FILL_LANDING_BEFORE_S, _FILL_LANDING_AFTER_S, _FILL_NAV_S = 45, 60, 30, 30


def validate_windows(windows: dict | None) -> dict:
    """Window (seconds before/after) per event type: the given values over the defaults, range-checked."""
    if windows is not None and not isinstance(windows, dict):
        raise ValueError("windows must be an object")
    merged = {t: dict(DEFAULT_WINDOWS[t]) for t in HIGHLIGHT_TYPES}
    for event_type, window in (windows or {}).items():
        if event_type not in merged:
            raise ValueError(f"unknown event type {event_type!r}")
        if not isinstance(window, dict) or set(window) - {"before_s", "after_s"}:
            raise ValueError(f"window of {event_type} needs before_s and after_s")
        for key, value in window.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_WINDOW_S:
                raise ValueError(f"{event_type}.{key} must be a number between 0 and {MAX_WINDOW_S}")
            merged[event_type][key] = value
    return merged


def _merge_windows(wins: list, gap_s: float) -> list:
    merged = []
    for w in sorted(wins, key=lambda w: w["start"]):
        if merged and w["start"] - merged[-1]["end"] < gap_s:
            last = merged[-1]
            last["end"] = max(last["end"], w["end"])
            last["event_types"] += [t for t in w["event_types"] if t not in last["event_types"]]
        else:
            merged.append({**w, "event_types": list(w["event_types"])})
    return merged


def _total(wins: list) -> float:
    return sum(w["end"] - w["start"] for w in wins)


def _overlaps(a: dict, wins: list) -> bool:
    return any(a["start"] < w["end"] and w["start"] < a["end"] for w in wins)


def _filler_windows(tel: dict, offset_s: float, video_duration: float) -> tuple:
    """Takeoff and landing windows, plus the 30 s chunks of non-static navigation they can be topped up with."""
    phases, t = classify_phases(tel), tel["t"]

    def clamp(a, b):
        return max(a, 0.0), min(b, video_duration)

    takeoff = landing = None
    for i, phase in enumerate(phases):
        if phase == "despegue" and takeoff is None:
            takeoff = clamp(t[i] - offset_s, t[i] - offset_s + _FILL_TAKEOFF_S)
        if phase == "rodaje" and i and phases[i - 1] == "aproximacion":
            touch = t[i] - offset_s
            landing = clamp(touch - _FILL_LANDING_BEFORE_S, touch + _FILL_LANDING_AFTER_S)
    steady = steady_flags(tel)
    chunks, run = [], None
    for i, phase in enumerate(phases + [None]):
        free = phase == "navegacion" and not steady[i]
        if free and run is None:
            run = i
        elif not free and run is not None:
            start = t[run] - offset_s
            while start + _FILL_NAV_S <= t[i - 1] - offset_s:
                chunks.append(clamp(start, start + _FILL_NAV_S))
                start += _FILL_NAV_S
            run = None
    return takeoff, landing, chunks


def propose_highlights(events: dict, tel: dict | None, offset_s: float, video_duration: float,
                       windows: dict | None = None, target_s: float = 540.0, min_s: float = 480.0,
                       max_s: float = 600.0, merge_gap_s: float = 5.0) -> dict:
    """Highlight windows in video time: combat events by priority up to target_s, topped up below min_s.

    events come from acmi.parse_acmi_events with the same offset (time_s already in video time). If the
    events fall short of min_s, takeoff, landing and spread navigation windows are added (reason "relleno"),
    which needs the player telemetry; without it the highlight is just shorter and a warning says so.
    """
    windows = validate_windows(windows)
    cands = []
    for rank, event_type in enumerate(HIGHLIGHT_TYPES):
        w = windows[event_type]
        for ev in events.get(_EVENT_KEYS[event_type], []):
            start, end = max(ev["time_s"] - w["before_s"], 0.0), min(ev["time_s"] + w["after_s"], video_duration)
            if end > start:
                cands.append((rank, start, {"start": start, "end": end, "event_types": [event_type]}))
    accepted = []
    for _, _, cand in sorted(cands, key=lambda c: c[:2]):
        trial = _merge_windows(accepted + [cand], merge_gap_s)
        if _total(trial) > max_s:
            continue
        accepted.append(cand)
        if _total(trial) >= target_s:
            break
    segments = [{**w, "reason": "evento"} for w in _merge_windows(accepted, merge_gap_s)]

    if _total(segments) < min_s and tel is not None:
        takeoff, landing, chunks = _filler_windows(tel, offset_s, video_duration)
        for label, span in (("despegue", takeoff), ("aterrizaje", landing)):
            win = span and {"start": span[0], "end": span[1], "event_types": [], "reason": "relleno", "label": label}
            if win and win["end"] > win["start"] and not _overlaps(win, segments):
                segments.append(win)
        free = [{"start": a, "end": b, "event_types": [], "reason": "relleno", "label": "navegacion"}
                for a, b in chunks]
        free = [c for c in free if not _overlaps(c, segments)]
        need = math.ceil(max(min_s - _total(segments), 0) / _FILL_NAV_S)
        if need and free:
            picks = free if need >= len(free) else [free[int((k + 0.5) * len(free) / need)] for k in range(need)]
            segments += picks
    segments.sort(key=lambda w: w["start"])
    duration = _total(segments)
    warnings = [] if duration >= min_s else [f"Highlight shorter than {min_s / 60:g} min: not enough material"]
    return {"segments": segments, "duration_s": duration, "warnings": warnings}


def to_render_plan(segments: list, video_duration: float) -> list:
    """Render plan of a highlight: its windows are kept and every gap between them is cut."""
    plan, cursor = [], 0.0
    for seg in sorted(segments, key=lambda s: s["start"]):
        if seg["start"] > cursor:
            plan.append({"start": cursor, "end": seg["start"], "action": "cut"})
        plan.append({"start": seg["start"], "end": seg["end"], "action": "keep"})
        cursor = seg["end"]
    if cursor < video_duration:
        plan.append({"start": cursor, "end": video_duration, "action": "cut"})
    return plan


def analyze_highlights(video_path: Path, acmi_path: Path, offset_s: float | None = None,
                       windows: dict | None = None, target_s: float = 540.0) -> dict:
    """Propose the highlight of a recording from its ACMI events and telemetry."""
    from dcs_meta import _get_video_duration

    windows = validate_windows(windows)
    duration = _get_video_duration(Path(video_path))
    offset = acmi.resolve_acmi_offset(Path(video_path), Path(acmi_path), offset_s)
    events = acmi.parse_acmi_events(Path(acmi_path), offset_s=offset)
    proposal = propose_highlights(events, read_player_telemetry(acmi_path), offset, duration, windows, target_s)
    resulting = summarize_plan(to_render_plan(proposal["segments"], duration), duration)["resulting_duration"]         if proposal["segments"] else 0.0
    return {**proposal, "resulting_duration": resulting, "video_duration": duration, "offset_s": offset}
