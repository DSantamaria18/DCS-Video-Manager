"""Thumbnail generation: frame scoring, colour grading, YouTube-style overlay."""

import os
import subprocess
from datetime import datetime
from pathlib import Path

# Font search paths for thumbnail overlay (Impact preferred, Arial Bold fallback)
_FONT_PATHS = [
    "C:/Windows/Fonts/impact.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/Library/Fonts/Impact.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
]


def _load_font(size: int):
    """Load Impact (or Arial Bold fallback) at the given point size."""
    from PIL import ImageFont
    for p in _FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
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
    from PIL import Image as _Img
    from PIL import ImageEnhance
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

    # Deferred import: avoids a circular import until TEC-01a's dcs_meta.py facade no
    # longer needs to reexport this module at load time (see BACKLOG.md TEC-01b).
    from dcs_meta import OUTPUT_PATH

    OUTPUT_PATH.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 — nombre de fichero en hora local de la máquina, intencional
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
        import io as _io

        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow not installed: pip install Pillow")

    # Deferred import: media (duration probing) is still owned by dcs_meta.py until
    # TEC-01c extracts it (see BACKLOG.md).
    from dcs_meta import _DURATION_ERRORS, _get_video_duration

    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))

    try:
        duration = _get_video_duration(video_path)
    except _DURATION_ERRORS as e:
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
        except (subprocess.CalledProcessError, OSError):
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
