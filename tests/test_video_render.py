"""Tests for video_render: pure planning logic plus an end-to-end render on a synthetic clip (FEA-09, 1b)."""

import random
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest

import video_render as vr


def _normal(start, end):
    return {"kind": "normal", "start": float(start), "end": float(end), "out_s": float(end - start)}


def _speed(start, end, factor, fase="navegacion"):
    return {"kind": "speed", "start": float(start), "end": float(end), "out_s": (end - start) / factor,
            "factor": float(factor), "fase": fase}


# ── pistas de audio ───────────────────────────────────────────────────────────

def test_usable_tracks_drops_empty_and_duplicated_tracks():
    game = [-50.0, -48.0, -52.0, -49.0]
    levels = [game, list(game), [-120.0] * 4, [-70.0, -65.0, -80.0, -62.0]]
    assert vr.usable_tracks(levels) == [0, 3]


def test_usable_tracks_keeps_a_near_copy_that_differs():
    game = [-50.0, -48.0, -52.0, -49.0]
    different = [x + 6 for x in game]
    assert vr.usable_tracks([game, different]) == [0, 1]


def test_usable_tracks_with_only_empty_tracks_returns_nothing():
    assert vr.usable_tracks([[-120.0] * 5, []]) == []


# ── música ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("fase, bucket", [("rodaje", "rodaje_despegue"), ("despegue", "rodaje_despegue"),
                                          ("navegacion", "navegacion"), ("aproximacion", "aproximacion_aterrizaje"),
                                          (None, "navegacion")])
def test_music_bucket_maps_flight_phases_to_folders(fase, bucket):
    assert vr.music_bucket(fase) == bucket


def test_pick_music_chooses_from_the_phase_folder_without_repeating(tmp_path):
    folder = tmp_path / "navegacion"
    folder.mkdir()
    for name in ("a.mp3", "b.wav", "notes.txt"):
        (folder / name).write_bytes(b"x")
    used, rng = set(), random.Random(1)
    first = vr.pick_music(tmp_path, "navegacion", rng, used)
    second = vr.pick_music(tmp_path, "navegacion", rng, used)
    assert {first.name, second.name} == {"a.mp3", "b.wav"}
    assert vr.pick_music(tmp_path, "navegacion", rng, used) in (first, second)    # agotadas: se vuelve a empezar


def test_pick_music_returns_none_without_folder_or_tracks(tmp_path):
    assert vr.pick_music(None, "navegacion", random.Random(0), set()) is None
    assert vr.pick_music(tmp_path, "navegacion", random.Random(0), set()) is None
    (tmp_path / "navegacion").mkdir()
    assert vr.pick_music(tmp_path, "navegacion", random.Random(0), set()) is None


# ── piezas y bloques ──────────────────────────────────────────────────────────

def test_renderable_pieces_drops_footage_too_short_for_a_fade():
    pieces = [_normal(0, 0.3), _speed(0.3, 100, 20), _normal(100, 110),
              {"kind": "cut", "start": 5, "end": 6, "out_s": 0}]
    kept = vr.renderable_pieces(pieces, 0.3)
    assert [p["kind"] for p in kept] == ["speed", "normal"]
    assert len(vr.renderable_pieces(pieces, 0.0)) == 3


def test_split_into_chunks_splits_a_normal_piece_and_keeps_all_footage():
    pieces = []
    for i in range(15):
        pieces += [_normal(i * 200, i * 200 + 60), _speed(i * 200 + 60, i * 200 + 200, 7)]
    chunks = vr.split_into_chunks(pieces, max_pieces=12)
    assert all(len(c) <= 13 for c in chunks) and len(chunks) > 1
    flat = [p for c in chunks for p in c]
    assert sum(p["out_s"] for p in flat) == pytest.approx(sum(p["out_s"] for p in pieces))
    for current, following in pairwise(chunks):
        assert current[-1]["kind"] == following[0]["kind"] == "normal"
        assert current[-1]["end"] == following[0]["start"]            # imagen continua: no hace falta fundido


def test_split_into_chunks_never_splits_a_sped_up_piece():
    pieces = [_speed(i * 100, i * 100 + 90, 9) for i in range(30)]
    assert len(vr.split_into_chunks(pieces, max_pieces=5)) == 1


def test_video_chunk_graph_chains_xfade_with_cumulative_offsets():
    chunk = [_normal(100, 110), _speed(110, 130, 4), _normal(130, 140)]
    graph = vr.video_chunk_graph(chunk, "60/1", 0.3)
    assert "trim=start=0.0000:end=10.0000" in graph               # relativo al inicio del bloque
    assert "setpts=(PTS-STARTPTS)/4" in graph
    assert "xfade=transition=fade:duration=0.3:offset=9.7000" in graph
    assert "offset=14.4000" in graph and graph.rstrip().endswith("[vout]")


def test_video_chunk_graph_without_fade_concatenates_and_single_piece_passes_through():
    chunk = [_normal(0, 10), _speed(10, 30, 4)]
    assert "concat=n=2:v=1:a=0[vout]" in vr.video_chunk_graph(chunk, "60/1", 0.0)
    assert "[v0]null[vout]" in vr.video_chunk_graph([_normal(0, 10)], "60/1", 0.3)


def test_audio_graph_fuses_tracks_uses_music_and_crossfades():
    pieces = [_normal(0, 10), _speed(10, 30, 4), _normal(30, 40)]
    graph, extra = vr.audio_graph(pieces, [0, 2], {1: Path("song.mp3")}, 0.3)
    assert extra == ["-i", "song.mp3"]
    assert "amix=inputs=2:normalize=0" in graph and "asplit=2[m0][m2]" in graph
    assert "[1:a]aresample" in graph and "afade=t=in" in graph
    assert graph.count("acrossfade=d=0.3") == 2 and "loudnorm" in graph and graph.rstrip().endswith("[aout]")


def test_audio_graph_adds_a_looping_background_bed_under_the_edit():
    pieces = [_normal(0, 10), _normal(20, 30)]
    graph, extra = vr.audio_graph(pieces, [0], {}, 0.3, bed=Path("bed.mp3"), bed_db=-20.0)
    assert extra == ["-i", "bed.mp3"]
    assert "[1:a]aresample" in graph and "aloop=loop=-1" in graph and "volume=-20.0dB" in graph
    assert "atrim=0:19.7000" in graph.split("[bed]")[0].splitlines()[-1]       # 10 + 10 - 0.3 de fundido
    assert "[joined][bed]amix=inputs=2:normalize=0:duration=first[mixed]" in graph
    assert "[mixed]loudnorm" in graph and "[joined]loudnorm" not in graph


def test_audio_graph_without_tracks_or_music_uses_silence():
    pieces = [_normal(0, 10), _speed(10, 30, 4)]
    graph, extra = vr.audio_graph(pieces, [], {}, 0.3)
    assert extra == [] and graph.count("anullsrc") == 2 and "amix" not in graph


def test_unique_output_path_never_overwrites(tmp_path):
    video = tmp_path / "2026-10-17_00-34-43.mkv"
    first = vr.unique_output_path(video, tmp_path)
    assert first.name == "2026-10-17_00-34-43_editado.mp4"
    first.write_bytes(b"x")
    assert vr.unique_output_path(video, tmp_path).name == "2026-10-17_00-34-43_editado_2.mp4"


# ── render real sobre un clip sintético ───────────────────────────────────────

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg/ffprobe not installed")


def _make_clip(path, seconds=40):
    """640x360 30 fps clip with 3 audio tracks: a tone, an identical copy and digital silence."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
           "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
           "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={seconds}",
           "-map", "0:v", "-map", "1:a", "-map", "2:a", "-map", "3:a", "-c:v", "libx264", "-preset", "ultrafast",
           "-c:a", "aac", str(path)]
    subprocess.run(cmd, check=True)


def _durations(path):
    out = {}
    for kind in ("v", "a"):
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", f"{kind}:0", "-show_entries",
                            "stream=duration", "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
        out[kind] = float(r.stdout.strip())
    return out


SEGMENTS = [{"start": 10, "end": 30, "action": "speed", "fase": "rodaje"}]
EXPECTED = 10 + 5 + 10 - 2 * 0.3          # normal + acelerado (20 s a x4) + normal, menos dos fundidos


@needs_ffmpeg
@pytest.mark.parametrize("max_pieces", [12, 2])    # 2 obliga a partir en bloques y unirlos sin recodificar
def test_render_edit_produces_the_expected_duration_in_sync(tmp_path, max_pieces):
    clip = tmp_path / "rec.mkv"
    _make_clip(clip)
    before = (clip.stat().st_size, clip.stat().st_mtime)
    progress = []

    result = vr.render_edit(clip, SEGMENTS, tmp_path / "edits", on_progress=lambda p, m: progress.append(p),
                            max_pieces=max_pieces)

    out = Path(result["output_path"])
    assert out.name == "rec_editado.mp4" and out.parent == tmp_path / "edits"
    d = _durations(out)
    assert d["v"] == pytest.approx(EXPECTED, abs=0.25) and d["a"] == pytest.approx(EXPECTED, abs=0.25)
    assert result["duration"] == pytest.approx(EXPECTED, abs=0.05)      # el clip real dura 40.02 s
    assert (clip.stat().st_size, clip.stat().st_mtime) == before                    # el original no se toca
    assert progress[-1] == 100 and progress == sorted(progress)
    assert not [p for p in (tmp_path / "edits").iterdir() if p.name.startswith(".edit_")]   # sin temporales
    assert any("1 of 3 audio tracks" in w for w in result["warnings"])
    assert any("no music" in w.lower() for w in result["warnings"])


@needs_ffmpeg
def test_render_edit_mixes_music_into_the_sped_up_section_and_never_overwrites(tmp_path):
    clip = tmp_path / "rec.mkv"
    _make_clip(clip)
    music = tmp_path / "music" / "rodaje_despegue"
    music.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=3", str(music / "song.wav")], check=True)

    first = vr.render_edit(clip, SEGMENTS, tmp_path / "edits", music_folder=str(tmp_path / "music"), seed=1)
    second = vr.render_edit(clip, SEGMENTS, tmp_path / "edits", music_folder=str(tmp_path / "music"), seed=1)

    assert not any("music" in w.lower() for w in first["warnings"])
    assert Path(second["output_path"]).name == "rec_editado_2.mp4"
    assert _durations(Path(first["output_path"]))["a"] == pytest.approx(EXPECTED, abs=0.25)


HIGHLIGHT_PLAN = [{"start": 0, "end": 5, "action": "cut"}, {"start": 5, "end": 15, "action": "keep"},
                  {"start": 15, "end": 25, "action": "cut"}, {"start": 25, "end": 35, "action": "keep"},
                  {"start": 35, "end": 40, "action": "cut"}]


@needs_ffmpeg
def test_render_edit_highlight_mixes_a_background_bed_and_warns_without_one(tmp_path):
    clip = tmp_path / "rec.mkv"
    _make_clip(clip)
    bed_dir = tmp_path / "music" / "highlight"
    bed_dir.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=880:duration=3", str(bed_dir / "song.wav")], check=True)

    with_bed = vr.render_edit(clip, HIGHLIGHT_PLAN, tmp_path / "edits", music_folder=str(tmp_path / "music"),
                              music_bed_db=-20.0, seed=1)
    without = vr.render_edit(clip, HIGHLIGHT_PLAN, tmp_path / "edits", music_folder=str(tmp_path / "none"),
                             music_bed_db=-20.0)

    expected = 20 - 0.3                     # dos ventanas de 10 s unidas con un fundido
    for result in (with_bed, without):
        d = _durations(Path(result["output_path"]))
        assert d["v"] == pytest.approx(expected, abs=0.25) and d["a"] == pytest.approx(expected, abs=0.25)
    assert not any("background music" in w.lower() for w in with_bed["warnings"])
    assert any("background music" in w.lower() for w in without["warnings"])


@needs_ffmpeg
def test_render_edit_rejects_an_edit_with_no_footage(tmp_path):
    clip = tmp_path / "rec.mkv"
    _make_clip(clip, seconds=10)
    with pytest.raises(ValueError, match="no footage"):
        vr.render_edit(clip, [{"start": 0, "end": 10, "action": "cut"}], tmp_path / "edits")
