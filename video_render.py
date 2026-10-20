"""Rendering of the automatic edit (FEA-09, phase 1b): ffmpeg commands and execution.

Video is rendered in chunks and joined without re-encoding, because the memory of a single filter graph grows
faster than linearly with its pieces (measured: 1 GB for 6 pieces, 2.6 GB for 20, 16 GB for 40). Chunk
boundaries fall in the middle of normal footage, where the image is continuous and needs no fade. Audio is
one separate, light graph (track fusion, music, fades, loudness) and a final mux copies both streams.
"""

import json
import random
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import video_edit

AUDIO_RATE = 48000
DEFAULT_CQ = 28                  # ~11 Mbps en NVENC frente a los ~10 Mbps de las grabaciones (medido, Fase 1b)
MAX_PIECES_PER_CHUNK = 12
MUSIC_GAIN = 0.35                # ponytail: ganancia fija; ajustar con el primer render real o medir con loudnorm
MUSIC_FADE_S = 1.0
BED_FOLDER = "highlight"         # música de fondo del highlight (Fase 2)
MUSIC_EXTENSIONS = (".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac")
EMPTY_TRACK_DB = -90.0           # una pista cuyo máximo no pasa de aquí está vacía (p. ej. micro en monojugador)
DUPLICATE_TOLERANCE_DB = 0.5
MIN_PIECE_FADE_RATIO = 2         # una pieza más corta que 2 fundidos no admite fundido a ambos lados
MUSIC_BUCKETS = {"rodaje": "rodaje_despegue", "despegue": "rodaje_despegue",
                 "navegacion": "navegacion", "aproximacion": "aproximacion_aterrizaje"}


# ── Sondeo y pistas de audio ──────────────────────────────────────────────────

def probe_media(video_path: Path) -> dict:
    """Return {duration, fps, audio_tracks, size} for a recording via ffprobe."""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams",
                        str(video_path)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       check=False)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {r.stderr.strip()[-300:]}")
    info = json.loads(r.stdout)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("The file has no video stream")
    return {"duration": float(info["format"]["duration"]), "fps": video.get("r_frame_rate", "60/1"),
            "audio_tracks": sum(1 for s in info["streams"] if s.get("codec_type") == "audio"),
            "size": int(info["format"].get("size", 0))}


def audio_levels(video_path: Path, track: int) -> list:
    """RMS level in dB for each second of one audio track (digital silence is reported as -120)."""
    r = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(video_path), "-map", f"0:a:{track}", "-vn",
        "-af", ("aresample=8000,asetnsamples=n=8000:p=0,astats=metadata=1:reset=1,"
                "ametadata=mode=print:key=lavfi.astats.Overall.RMS_level:file=-"), "-f", "null", "-",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
    levels = []
    for line in r.stdout.splitlines():
        if "RMS_level=" in line:
            value = line.split("=")[1].strip()
            levels.append(-120.0 if value in ("-inf", "inf") else float(value))
    return levels


def usable_tracks(levels: list, empty_db: float = EMPTY_TRACK_DB, tolerance_db: float = DUPLICATE_TOLERANCE_DB) -> list:
    """Indices of the audio tracks worth mixing: not empty and not a copy of one already kept."""
    kept = []
    for i, series in enumerate(levels):
        if not series or max(series) <= empty_db:
            continue
        duplicate = any(
            len(series) == len(levels[j])
            and sum(abs(a - b) <= tolerance_db for a, b in zip(series, levels[j])) >= 0.99 * len(series)
            for j in kept)
        if not duplicate:
            kept.append(i)
    return kept


# ── Música por fase de vuelo ──────────────────────────────────────────────────

def music_bucket(fase: str | None) -> str:
    return MUSIC_BUCKETS.get(fase or "", "navegacion")


def pick_music(folder: str | Path | None, bucket: str, rng: random.Random, used: set) -> Path | None:
    """Random track from <folder>/<bucket>, not repeating one already used until all have been."""
    if not folder:
        return None
    directory = Path(folder) / bucket
    if not directory.is_dir():
        return None
    tracks = sorted(p for p in directory.iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS)
    if not tracks:
        return None
    fresh = [t for t in tracks if t not in used] or tracks
    choice = rng.choice(fresh)
    used.add(choice)
    return choice


# ── Piezas, bloques y grafos ──────────────────────────────────────────────────

def renderable_pieces(pieces: list, fade_s: float) -> list:
    """Kept pieces that are long enough for a fade on both sides (shorter ones are dropped)."""
    minimum = MIN_PIECE_FADE_RATIO * fade_s + 0.1 if fade_s else 0.0
    return [p for p in video_edit.kept_pieces(pieces) if p["out_s"] >= minimum]


def split_into_chunks(pieces: list, max_pieces: int = MAX_PIECES_PER_CHUNK) -> list:
    """Group pieces into chunks of about max_pieces, splitting a long normal piece at each boundary.

    The two halves of a split piece are continuous footage, so the join between chunks needs no fade. A chunk
    holds at most max_pieces + 1 pieces, and more only while no normal piece long enough to split turns up.
    """
    chunks, current = [], []
    for piece in pieces:
        if len(current) >= max_pieces - 1 and piece["kind"] == "normal" and piece["out_s"] >= 4:
            middle = piece["start"] + (piece["end"] - piece["start"]) / 2
            first = {**piece, "end": middle, "out_s": middle - piece["start"]}
            second = {**piece, "start": middle, "out_s": piece["end"] - middle}
            current.append(first)
            chunks.append(current)
            current = [second]
        else:
            current.append(piece)
    if current:
        chunks.append(current)
    return chunks


def chunk_length(chunk: list, fade_s: float) -> float:
    return sum(p["out_s"] for p in chunk) - fade_s * max(0, len(chunk) - 1)


def video_chunk_graph(chunk: list, fps: str, fade_s: float) -> str:
    """Filter graph for one chunk; trim times are relative to the chunk's input (-ss chunk[0].start)."""
    base = chunk[0]["start"]
    lines = []
    for i, p in enumerate(chunk):
        factor = p.get("factor") or 1.0
        speed = "" if factor == 1.0 else f"/{factor:g}"
        lines.append(f"[0:v:0]trim=start={p['start'] - base:.4f}:end={p['end'] - base:.4f},"
                     f"setpts=(PTS-STARTPTS){speed},fps={fps},settb=1/90000[v{i}]")
    if len(chunk) == 1:
        lines.append("[v0]null[vout]")
    elif fade_s:
        acc, cur = chunk[0]["out_s"], "[v0]"
        for i in range(1, len(chunk)):
            out = "[vout]" if i == len(chunk) - 1 else f"[x{i}]"
            lines.append(f"{cur}[v{i}]xfade=transition=fade:duration={fade_s}:offset={acc - fade_s:.4f}{out}")
            acc += chunk[i]["out_s"] - fade_s
            cur = out
    else:
        labels = "".join(f"[v{i}]" for i in range(len(chunk)))
        lines.append(f"{labels}concat=n={len(chunk)}:v=1:a=0[vout]")
    return ";\n".join(lines)


def audio_graph(pieces: list, tracks: list, music: dict, fade_s: float, bed: Path | None = None,
                bed_db: float = -20.0) -> tuple:
    """(graph, extra_input_args) for the whole edit's audio.

    Normal pieces use the fused usable tracks; sped-up pieces use their music (index in `music` -> Path) or
    silence. Input 0 is the recording; each music file is one more input, in the order of `music`. A `bed`
    (highlight) is the last input: it loops under the whole edit, bed_db below it, fading in and out.
    """
    lines, extra, music_input = [], [], {}
    normals = [i for i, p in enumerate(pieces) if p["kind"] == "normal"]
    if tracks and normals:
        labels = []
        for t in tracks:
            lines.append(f"[0:a:{t}]aresample={AUDIO_RATE},aformat=channel_layouts=stereo[t{t}]")
            labels.append(f"[t{t}]")
        if len(tracks) == 1:
            lines.append(f"{labels[0]}anull[mix]")
        else:
            lines.append(f"{''.join(labels)}amix=inputs={len(tracks)}:normalize=0:duration=longest[mix]")
        if len(normals) > 1:
            lines.append("[mix]asplit=" + str(len(normals)) + "".join(f"[m{i}]" for i in normals))
        else:
            lines.append(f"[mix]anull[m{normals[0]}]")
    for n, (index, path) in enumerate(sorted(music.items()), start=1):
        extra += ["-i", str(path)]
        music_input[index] = n
    for i, p in enumerate(pieces):
        out = p["out_s"]
        if p["kind"] == "normal":
            if tracks:
                lines.append(f"[m{i}]atrim=start={p['start']:.4f}:end={p['end']:.4f},asetpts=PTS-STARTPTS[a{i}]")
            else:
                lines.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{out:.4f},asetpts=PTS-STARTPTS[a{i}]")
        elif i in music_input:
            fade = min(MUSIC_FADE_S, out / 2)
            lines.append(f"[{music_input[i]}:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,"
                         f"aloop=loop=-1:size=2147483647,atrim=0:{out:.4f},asetpts=PTS-STARTPTS,"
                         f"volume={MUSIC_GAIN},afade=t=in:d={fade:.3f},afade=t=out:st={out - fade:.4f}:d={fade:.3f}[a{i}]")
        else:
            lines.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{out:.4f},asetpts=PTS-STARTPTS[a{i}]")
    if len(pieces) == 1:
        lines.append("[a0]anull[joined]")
    elif fade_s:
        cur = "[a0]"
        for i in range(1, len(pieces)):
            out = "[joined]" if i == len(pieces) - 1 else f"[c{i}]"
            lines.append(f"{cur}[a{i}]acrossfade=d={fade_s}{out}")
            cur = out
    else:
        lines.append("".join(f"[a{i}]" for i in range(len(pieces))) + f"concat=n={len(pieces)}:v=0:a=1[joined]")
    source = "[joined]"
    if bed:
        total = sum(p["out_s"] for p in pieces) - fade_s * (len(pieces) - 1)
        fade = min(MUSIC_FADE_S, total / 2)
        extra += ["-i", str(bed)]
        lines.append(f"[{len(music) + 1}:a]aresample={AUDIO_RATE},aformat=channel_layouts=stereo,"
                     f"aloop=loop=-1:size=2147483647,atrim=0:{total:.4f},asetpts=PTS-STARTPTS,volume={bed_db}dB,"
                     f"afade=t=in:d={fade:.3f},afade=t=out:st={total - fade:.4f}:d={fade:.3f}[bed]")
        lines.append("[joined][bed]amix=inputs=2:normalize=0:duration=first[mixed]")
        source = "[mixed]"
    lines.append(f"{source}loudnorm=I=-16:TP=-1.5:LRA=11,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]")
    return ";\n".join(lines), extra


def unique_output_path(video_path: Path, out_dir: Path) -> Path:
    """<out_dir>/<name>_editado.mp4, never an existing file (a numeric suffix is added instead)."""
    base = Path(video_path).stem + "_editado"
    candidate, n = Path(out_dir) / f"{base}.mp4", 2
    while candidate.exists():
        candidate = Path(out_dir) / f"{base}_{n}.mp4"
        n += 1
    return candidate


# ── Ejecución ─────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _nvenc_works() -> bool:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256",
                        "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, check=False)
    return r.returncode == 0


def encoder_args(cq: int = DEFAULT_CQ) -> dict:
    """NVENC when the GPU encoder really works, libx264 otherwise (e.g. CI)."""
    if _nvenc_works():
        return {"name": "h264_nvenc", "hwaccel": ["-hwaccel", "cuda"],
                "args": ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(cq), "-b:v", "0", "-pix_fmt", "yuv420p"]}
    return {"name": "libx264", "hwaccel": [],
            "args": ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(cq), "-pix_fmt", "yuv420p"]}


def _run_ffmpeg(args: list, expected_s: float | None = None, on_progress=None) -> None:
    proc = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
                             "-progress", "pipe:1", *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    for line in proc.stdout:
        if on_progress and expected_s and line.startswith("out_time_us="):
            try:
                on_progress(min(1.0, max(0.0, int(line.split("=")[1]) / 1e6 / expected_s)))
            except ValueError:
                pass
    err = proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed: {err.strip()[-500:]}")


def _concat_entry(path: Path) -> str:
    return "file '" + str(path).replace("\\", "/").replace("'", "'\\''") + "'"


def render_edit(video_path: Path, segments: list, out_dir: Path, *, fade_s: float = video_edit.DEFAULT_FADE_S,
                cq: int = DEFAULT_CQ, music_folder: str | None = None, music_bed_db: float | None = None,
                on_progress=None,
                max_pieces: int = MAX_PIECES_PER_CHUNK, seed: int | None = None) -> dict:
    """Render the reviewed edit to <out_dir>/<name>_editado.mp4 and return {output_path, duration, warnings}.

    Never touches the original or an existing file; temporary files live in a hidden folder inside out_dir.
    music_bed_db (highlight) mixes a track of <music_folder>/highlight under the whole edit at that level.
    """
    video_path, out_dir = Path(video_path), Path(out_dir)
    progress = on_progress or (lambda pct, msg: None)
    media = probe_media(video_path)
    pieces = renderable_pieces(video_edit.build_pieces(segments, media["duration"]), fade_s)
    if not pieces:
        raise ValueError("The edit leaves no footage")
    out_dir.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out_dir).free < media["size"]:
        raise RuntimeError("Not enough free disk space for the rendered video")
    warnings = []

    levels = [audio_levels(video_path, t) for t in range(media["audio_tracks"])]
    tracks = usable_tracks(levels)
    if not tracks:
        warnings.append("No usable audio track: normal sections are silent")
    elif len(tracks) < media["audio_tracks"]:
        warnings.append(f"Using {len(tracks)} of {media['audio_tracks']} audio tracks (the rest are empty or duplicated)")

    rng, used, music = random.Random(seed), set(), {}
    for i, p in enumerate(pieces):
        if p["kind"] == "speed":
            track = pick_music(music_folder, music_bucket(p.get("fase")), rng, used)
            if track:
                music[i] = track
    if any(p["kind"] == "speed" for p in pieces) and len(music) < sum(p["kind"] == "speed" for p in pieces):
        warnings.append("Some sped-up sections have no music (music folder not set or empty): they are silent")

    bed = None
    if music_bed_db is not None:
        bed = pick_music(music_folder, BED_FOLDER, rng, used)
        if not bed:
            warnings.append(f"No background music (no tracks in '{BED_FOLDER}' of the music folder): the highlight has none")

    encoder = encoder_args(cq)
    chunks = split_into_chunks(pieces, max_pieces)
    total = sum(chunk_length(c, fade_s) for c in chunks)
    tmp = Path(tempfile.mkdtemp(prefix=".edit_", dir=out_dir))
    try:
        done = 0.0
        chunk_files = []
        for n, chunk in enumerate(chunks):
            length = chunk_length(chunk, fade_s)
            graph_file, out = tmp / f"chunk{n}.graph", tmp / f"chunk{n}.mp4"
            graph_file.write_text(video_chunk_graph(chunk, media["fps"], fade_s), encoding="utf-8")
            base, span = chunk[0]["start"], chunk[-1]["end"] - chunk[0]["start"]
            base_pct = 85.0 * done / total
            _run_ffmpeg([*encoder["hwaccel"], "-ss", f"{base:.4f}", "-t", f"{span:.4f}", "-i", str(video_path),
                         "-filter_complex_script", str(graph_file), "-map", "[vout]", "-an", *encoder["args"], str(out)],
                        length, lambda f, b=base_pct, w=85.0 * length / total, n=n: progress(b + w * f, f"Rendering video {n + 1}/{len(chunks)}"))
            chunk_files.append(out)
            done += length

        progress(85, "Rendering audio")
        audio_file, audio_graph_file = tmp / "audio.m4a", tmp / "audio.graph"
        graph, extra = audio_graph(pieces, tracks, music, fade_s, bed, music_bed_db or -20.0)
        audio_graph_file.write_text(graph, encoding="utf-8")
        _run_ffmpeg(["-i", str(video_path), *extra, "-filter_complex_script", str(audio_graph_file), "-map", "[aout]",
                     "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), str(audio_file)])

        progress(95, "Joining")
        listing = tmp / "chunks.txt"
        listing.write_text("\n".join(_concat_entry(f) for f in chunk_files) + "\n", encoding="utf-8")
        joined = tmp / "final.mp4"
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(listing), "-i", str(audio_file), "-map", "0:v:0",
                     "-map", "1:a:0", "-c", "copy", "-movflags", "+faststart", str(joined)])
        final = unique_output_path(video_path, out_dir)
        shutil.move(str(joined), str(final))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    progress(100, "Done")
    return {"output_path": str(final), "duration": total, "warnings": warnings, "encoder": encoder["name"],
            "chunks": len(chunks)}
