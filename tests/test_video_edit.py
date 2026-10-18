"""Tests for video_edit: dead-time proposal from ACMI telemetry (FEA-09, Phase 1a)."""

import zipfile

import pytest

import video_edit


def _tel(*blocks):
    """Build 1 Hz telemetry from (seconds, gear, ias_kt, agl, alt, hdm) blocks; ACMI time starts at 0."""
    tel = {k: [] for k in ("t", "alt", "ias_kt", "agl", "gear", "hdm", "roll", "pitch")}
    t = 0
    for seconds, gear, ias, agl, alt, hdm in blocks:
        for i in range(seconds):
            tel["t"].append(float(t))
            tel["alt"].append(float(alt))
            tel["ias_kt"].append(float(ias))
            tel["agl"].append(float(agl))
            tel["gear"].append(float(gear))
            tel["hdm"].append(float(hdm))
            tel["roll"].append(0.0)
            tel["pitch"].append(0.0)
            t += 1
    return tel


GROUND = (200, 1, 20, 5, 5, 0)
TAKEOFF = (30, 1, 150, 5, 5, 0)
CRUISE = (570, 0, 300, 6000, 6000, 90)
APPROACH = (60, 1, 150, 300, 300, 270)
ROLLOUT = (40, 1, 30, 5, 5, 270)


# ── fases ─────────────────────────────────────────────────────────────────────

def test_classify_phases_follows_gear_speed_and_height():
    phases = video_edit.classify_phases(_tel(GROUND, TAKEOFF, CRUISE, APPROACH, ROLLOUT))
    assert phases[100] == "rodaje"
    assert phases[215] == "despegue"
    assert phases[500] == "navegacion"
    assert phases[830] == "aproximacion"
    assert phases[-5] == "rodaje"


def test_classify_phases_ignores_blips_shorter_than_15_seconds():
    tel = _tel((100, 0, 300, 6000, 6000, 90), (5, 1, 150, 300, 300, 90), (100, 0, 300, 6000, 6000, 90))
    assert set(video_edit.classify_phases(tel)) == {"navegacion"}


# ── tramos estáticos ──────────────────────────────────────────────────────────

def test_steady_flags_mark_constant_cruise_but_not_manoeuvring():
    steady = video_edit.steady_flags(_tel((200, 0, 300, 6000, 6000, 90)))
    assert steady[60] and steady[120]
    manoeuvring = _tel((200, 0, 300, 6000, 6000, 90))
    manoeuvring["alt"] = [6000 + (300 if (i // 10) % 2 else 0) for i in range(200)]
    assert not any(video_edit.steady_flags(manoeuvring))


# ── propuesta de tramos ───────────────────────────────────────────────────────

def test_propose_segments_finds_ground_and_cruise_with_margins():
    tel = _tel(GROUND, TAKEOFF, CRUISE, APPROACH)
    segs = video_edit.propose_segments(tel, event_times=[], offset_s=0.0, video_duration=860.0)
    ground = segs[0]
    assert ground["fase"] == "rodaje"
    assert ground["start"] == pytest.approx(10.0) and ground["end"] == pytest.approx(189.0)
    assert segs[1]["fase"] == "navegacion"
    assert all(s["action"] == "speed" for s in segs)


def test_propose_segments_leaves_combat_untouched():
    tel = _tel(GROUND, TAKEOFF, CRUISE, APPROACH)
    segs = video_edit.propose_segments(tel, event_times=[500.0], offset_s=0.0, video_duration=860.0)
    cruise = [s for s in segs if s["fase"] == "navegacion"]
    assert len(cruise) == 2
    assert cruise[0]["end"] < 480 and cruise[1]["start"] > 520


def test_propose_segments_shifts_to_video_time_and_clamps_to_video_start():
    tel = _tel(GROUND, TAKEOFF, CRUISE, APPROACH)
    segs = video_edit.propose_segments(tel, event_times=[], offset_s=50.0, video_duration=810.0)
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == pytest.approx(139.0)
    assert all(0 <= s["start"] < s["end"] <= 810.0 for s in segs)


def test_propose_segments_drops_runs_shorter_than_a_minute():
    tel = _tel((50, 1, 20, 5, 5, 0), CRUISE)
    segs = video_edit.propose_segments(tel, event_times=[], offset_s=0.0, video_duration=620.0)
    assert [s["fase"] for s in segs] == ["navegacion"]


# ── velocidad ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("length, factor, out", [
    (60, 4.0, 15.0),       # por debajo del mínimo de 4x
    (200, 10.0, 20.0),     # objetivo de 20 s
    (320, 16.0, 20.0),     # justo en el máximo
])
def test_speed_plan_targets_twenty_seconds_between_4x_and_16x(length, factor, out):
    plan = video_edit.speed_plan(length)
    assert plan["factor"] == pytest.approx(factor)
    assert plan["out_s"] == pytest.approx(out)
    assert plan["cut_s"] == 0


def test_speed_plan_cuts_what_16x_cannot_absorb():
    plan = video_edit.speed_plan(582)
    assert plan["factor"] == 16.0
    assert plan["out_s"] == pytest.approx(20.0)
    assert plan["cut_s"] == pytest.approx(262.0)


def test_speed_plan_manual_speed_overrides_without_cutting():
    plan = video_edit.speed_plan(582, speed=8.0)
    assert plan["factor"] == 8.0 and plan["cut_s"] == 0
    assert plan["out_s"] == pytest.approx(72.75)


# ── resumen del plan ──────────────────────────────────────────────────────────

def test_summarize_plan_speed_segment_with_fades():
    segs = [{"start": 100, "end": 400, "action": "speed", "fase": "navegacion"}]
    out = video_edit.summarize_plan(segs, 1000.0, fade_s=0.3)
    assert out["segments"][0]["factor"] == pytest.approx(15.0)
    assert out["segments"][0]["out_s"] == pytest.approx(20.0)
    assert out["resulting_duration"] == pytest.approx(100 + 20 + 600 - 2 * 0.3)


def test_summarize_plan_cut_and_keep_actions():
    cut = video_edit.summarize_plan([{"start": 100, "end": 400, "action": "cut"}], 1000.0, fade_s=0.3)
    assert cut["resulting_duration"] == pytest.approx(100 + 600 - 0.3)
    keep = video_edit.summarize_plan([{"start": 100, "end": 400, "action": "keep"}], 1000.0, fade_s=0.0)
    assert keep["resulting_duration"] == pytest.approx(1000.0)


@pytest.mark.parametrize("segments, fragment", [
    ([{"start": 10, "end": 5, "action": "cut"}], "start"),
    ([{"start": 0, "end": 2000, "action": "cut"}], "video"),
    ([{"start": 0, "end": 100, "action": "cut"}, {"start": 50, "end": 150, "action": "cut"}], "overlap"),
    ([{"start": 0, "end": 100, "action": "explode"}], "action"),
    ([{"start": 0, "end": 100, "action": "speed", "speed": 0.5}], "speed"),
])
def test_summarize_plan_rejects_invalid_segments(segments, fragment):
    with pytest.raises(ValueError, match=fragment):
        video_edit.summarize_plan(segments, 1000.0)


# ── telemetría del ACMI ───────────────────────────────────────────────────────

_ACMI = """FileType=text/acmi/tacview
FileVersion=2.2
0,ReferenceTime=2016-06-22T05:00:00Z
#0
a1,T=1|2|10,Type=Air+FixedWing,Name=AI-Su-27,Pilot=Bot
p1,T=1|2|100,Type=Air+FixedWing,Name=FA-18C_hornet,Pilot=Cylon,IAS=50,AGL=22,LandingGear=1,HDM=90,RollControlPosition=0.1,PitchControlPosition=-0.2
#1
p1,T=1|2|110,IAS=60
a1,T=1|2|12
#3
p1,T=1|2|130,LandingGear=0,IAS=100
"""


def _write(tmp_path, text, zipped=False):
    f = tmp_path / "m.acmi"
    f.write_text(text, encoding="utf-8")
    if not zipped:
        return f
    z = tmp_path / "m.zip.acmi"
    with zipfile.ZipFile(z, "w") as zf:
        zf.write(f, "inner.txt.acmi")
    return z


@pytest.mark.parametrize("zipped", [False, True])
def test_read_player_telemetry_picks_the_cockpit_aircraft_and_samples_at_1hz(tmp_path, zipped):
    tel = video_edit.read_player_telemetry(_write(tmp_path, _ACMI, zipped))
    assert tel["t"][:4] == [0.0, 1.0, 2.0, 3.0]
    assert tel["alt"][:4] == [100.0, 110.0, 110.0, 130.0]
    assert tel["gear"][:4] == [1.0, 1.0, 1.0, 0.0]
    assert tel["ias_kt"][0] == pytest.approx(50 * 1.94384, rel=1e-3)   # el ACMI guarda m/s
    assert tel["agl"][0] == 22.0


def test_read_player_telemetry_without_cockpit_data_raises(tmp_path):
    text = "FileType=text/acmi/tacview\nFileVersion=2.2\n#0\na1,T=1|2|10,Type=Air+FixedWing,Name=AI,Pilot=Bot\n#5\n"
    with pytest.raises(ValueError, match="player"):
        video_edit.read_player_telemetry(_write(tmp_path, text))


# ── piezas de la edición (compartidas por el resumen y el render) ─────────────

def test_build_pieces_orders_normal_speed_and_cut_markers():
    segs = [{"start": 100, "end": 400, "action": "speed", "fase": "navegacion"},
            {"start": 500, "end": 600, "action": "cut"}]
    pieces = video_edit.build_pieces(segs, 1000.0)
    assert [(p["kind"], p["start"], p["end"]) for p in pieces] == [
        ("normal", 0, 100), ("speed", 100, 400), ("normal", 400, 500), ("cut", 500, 600), ("normal", 600, 1000)]
    assert pieces[1]["factor"] == pytest.approx(15.0) and pieces[1]["fase"] == "navegacion"
    assert pieces[1]["out_s"] == pytest.approx(20.0)


def test_build_pieces_merges_keep_into_the_neighbouring_normal_footage():
    pieces = video_edit.build_pieces([{"start": 100, "end": 400, "action": "keep"}], 1000.0)
    assert [(p["kind"], p["start"], p["end"]) for p in pieces] == [("normal", 0, 1000)]


def test_build_pieces_speed_covers_only_the_accelerated_part():
    pieces = video_edit.build_pieces([{"start": 0, "end": 582, "action": "speed", "fase": "rodaje"}], 1000.0)
    speed = pieces[0]
    assert speed["end"] == pytest.approx(320.0)          # 16x * 20 s; el resto se corta
    assert pieces[1]["kind"] == "normal" and pieces[1]["start"] == 582
