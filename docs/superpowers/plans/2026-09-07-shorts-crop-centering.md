# Recorte 9:16 de Shorts centrado en la acción — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el recorte 9:16 de `detect_short_clips()` (`dcs_meta.py`) se desplace hacia la zona
del frame con más detalle/actividad visual, en vez de recortar siempre el centro geométrico fijo.

**Architecture:** Dos funciones nuevas en `dcs_meta.py`: `_score_band_activity()` puntúa franjas
verticales de un frame por detalle de bordes (Pillow, misma técnica que
`thumbnail._score_frame`), y `_detect_action_center_frac()` muestrea varios frames dentro de la
ventana del clip, agrega las puntuaciones por franja, y devuelve la fracción horizontal (0.0-1.0)
de la franja ganadora — con fallback a `0.5` (centro, comportamiento actual) ante cualquier fallo.
`detect_short_clips()` usa ese valor para calcular el offset X del filtro `crop` de ffmpeg.

**Tech Stack:** Python 3.10+, Pillow (`ImageFilter`, `ImageStat`, ya en `requirements.txt`),
ffmpeg (subprocess, ya usado en el resto del fichero), pytest + `monkeypatch` (mismo patrón que
`tests/test_dcs_meta.py`).

## Global Constraints

- Offset fijo por clip (no paneo dentro del propio clip).
- Cero llamadas nuevas a Gemini u otra API externa — solo `ffmpeg` local y `Pillow`.
- Cualquier fallo en el análisis (ffmpeg no instalado, error de proceso, imagen ilegible) debe caer
  a `center_frac=0.5` sin lanzar excepción — el Short se sigue generando siempre.
- La resolución de salida sigue siendo 1080x1920; solo cambia el offset X del `crop`.
- No se toca `_collect_candidate_timestamps`, la selección de ventana/timestamp, ni el resto del
  pipeline de `detect_short_clips()`.

---

### Task 1: `_score_band_activity` — puntuación de detalle por franja vertical

**Files:**
- Modify: `dcs_meta.py` (junto a `detect_short_clips`, ~línea 1652)
- Test: `tests/test_dcs_meta.py`

**Interfaces:**
- Produces: `_score_band_activity(img, n_bands: int = 8) -> list[float]` — recibe una imagen PIL
  (`PIL.Image.Image`), la divide en `n_bands` franjas verticales iguales, y devuelve una lista de
  `n_bands` puntuaciones de detalle de bordes (una por franja, de izquierda a derecha).

- [ ] **Step 1: Write the failing test**

Añadir en `tests/test_dcs_meta.py`, en la sección `# ── detect_short_clips ──`, antes de
`_make_fake_process`:

```python
# ── _score_band_activity ────────────────────────────────────────────────────────

def _make_edge_image(edges_on="right", w=640, h=360):
    """Solid image with a checkerboard strip (strong edges) on one half only."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    start_x = w // 2 if edges_on == "right" else 0
    end_x = w if edges_on == "right" else w // 2
    for x in range(start_x, end_x, 10):
        draw.rectangle([x, 0, x + 5, h], fill=(255, 255, 255))
    return img


def test_score_band_activity_finds_edges_on_right_side():
    img = _make_edge_image(edges_on="right")
    scores = dcs_meta._score_band_activity(img, n_bands=8)
    assert len(scores) == 8
    winning_band = max(range(8), key=lambda b: scores[b])
    assert winning_band >= 4  # right half of the frame


def test_score_band_activity_finds_edges_on_left_side():
    img = _make_edge_image(edges_on="left")
    scores = dcs_meta._score_band_activity(img, n_bands=8)
    winning_band = max(range(8), key=lambda b: scores[b])
    assert winning_band < 4  # left half of the frame
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k score_band_activity -v --no-cov`
Expected: FAIL — `AttributeError: module 'dcs_meta' has no attribute '_score_band_activity'`

- [ ] **Step 3: Write minimal implementation**

En `dcs_meta.py`, justo antes de `def detect_short_clips(` (~línea 1652):

```python
def _score_band_activity(img, n_bands: int = 8) -> list[float]:
    """Split img into n_bands vertical strips and return an edge-detail score per band,
    left to right. Same edge-detection technique as thumbnail._score_frame, implemented
    independently here to avoid coupling dcs_meta.py to the thumbnail module."""
    from PIL import ImageFilter, ImageStat

    gray = img.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    w, h = edges.size
    band_w = w / n_bands

    scores = []
    for i in range(n_bands):
        left = int(i * band_w)
        right = int((i + 1) * band_w) if i < n_bands - 1 else w
        band = edges.crop((left, 0, right, h))
        scores.append(ImageStat.Stat(band).mean[0])
    return scores
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k score_band_activity -v --no-cov`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add dcs_meta.py tests/test_dcs_meta.py
git commit -m "feat(shorts-crop): añade _score_band_activity para puntuar detalle por franja"
```

---

### Task 2: `_detect_action_center_frac` — offset horizontal a partir de frames de muestra

**Files:**
- Modify: `dcs_meta.py`
- Test: `tests/test_dcs_meta.py`

**Interfaces:**
- Consumes: `_score_band_activity(img, n_bands) -> list[float]` (Task 1).
- Produces: `_detect_action_center_frac(video_path: Path, start: float, duration: float,
  n_samples: int = 5, n_bands: int = 8) -> float` — fracción horizontal (0.0-1.0) de la franja
  ganadora, o `0.5` si `duration <= 0` o si todas las muestras fallan.

- [ ] **Step 1: Write the failing test**

```python
# ── _detect_action_center_frac ──────────────────────────────────────────────────

def test_detect_action_center_frac_duration_zero_returns_half(tmp_path):
    video = tmp_path / "v.mp4"
    result = dcs_meta._detect_action_center_frac(video, start=0.0, duration=0.0)
    assert result == 0.5


def test_detect_action_center_frac_all_samples_fail_returns_half(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"

    def failing_run(*a, **kw):
        raise OSError("ffmpeg not found")

    monkeypatch.setattr("subprocess.run", failing_run)
    result = dcs_meta._detect_action_center_frac(video, start=0.0, duration=30.0)
    assert result == 0.5


def test_detect_action_center_frac_uses_winning_band(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("subprocess.run", lambda *a, **kw: _make_fake_process())
    monkeypatch.setattr("PIL.Image.open", lambda path: FakeImage())
    # Band index 6 (of 8) always wins, regardless of the sampled image.
    monkeypatch.setattr(dcs_meta, "_score_band_activity",
                         lambda img, n_bands=8: [0.0] * 6 + [10.0] + [0.0])

    result = dcs_meta._detect_action_center_frac(video, start=0.0, duration=30.0,
                                                   n_samples=3, n_bands=8)
    assert result == (6 + 0.5) / 8
```

Nota: `_make_fake_process` ya existe en el fichero (definida junto a los tests de
`detect_short_clips`, unas líneas más abajo); si estos nuevos tests se colocan antes de esa
definición, muévela justo encima de esta sección o impórtala igual (está en el mismo módulo de
test, no hace falta mover nada si Python ya la ha definido en tiempo de ejecución del fichero —
pytest carga el fichero completo antes de ejecutar los tests, así que el orden de definición no
importa aquí).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k detect_action_center_frac -v --no-cov`
Expected: FAIL — `AttributeError: module 'dcs_meta' has no attribute '_detect_action_center_frac'`

- [ ] **Step 3: Write minimal implementation**

En `dcs_meta.py`, justo debajo de `_score_band_activity`:

```python
def _detect_action_center_frac(video_path: Path, start: float, duration: float,
                                 n_samples: int = 5, n_bands: int = 8) -> float:
    """Sample n_samples frames within [start, start+duration] and return the horizontal
    center (0.0-1.0 fraction of frame width) of the band with the most aggregated edge
    detail. Falls back to 0.5 (frame center) if duration <= 0 or every sample fails —
    this must never raise, since a failed analysis should never block Shorts generation."""
    if duration <= 0:
        return 0.5

    from PIL import Image

    tmp_dir = Path(os.environ.get("TEMP", "/tmp"))
    totals = [0.0] * n_bands
    sampled = 0
    interval = duration / (n_samples + 1)

    for i in range(1, n_samples + 1):
        timestamp = start + interval * i
        tmp_path = tmp_dir / f"dcs_crop_sample_{os.getpid()}_{i}.jpg"
        try:
            subprocess.run([
                "ffmpeg", "-y", "-ss", str(timestamp),
                "-i", str(video_path),
                "-vframes", "1", "-q:v", "5",
                "-vf", "scale=640:-1",
                str(tmp_path)
            ], capture_output=True, check=True)
            with Image.open(tmp_path) as img:
                band_scores = _score_band_activity(img, n_bands)
            for b in range(n_bands):
                totals[b] += band_scores[b]
            sampled += 1
        except (subprocess.CalledProcessError, OSError):
            pass
        finally:
            tmp_path.unlink(missing_ok=True)

    if sampled == 0:
        return 0.5

    best_band = max(range(n_bands), key=lambda b: totals[b])
    return (best_band + 0.5) / n_bands
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k detect_action_center_frac -v --no-cov`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add dcs_meta.py tests/test_dcs_meta.py
git commit -m "feat(shorts-crop): añade _detect_action_center_frac con fallback a 0.5"
```

---

### Task 3: Integrar el offset en el filtro `crop` de `detect_short_clips`

**Files:**
- Modify: `dcs_meta.py:1722` (dentro de `detect_short_clips`)
- Test: `tests/test_dcs_meta.py`

**Interfaces:**
- Consumes: `_detect_action_center_frac(video_path, start, duration) -> float` (Task 2).
- Produces: el filtro `-vf` pasado a ffmpeg en `detect_short_clips()` incorpora el offset
  calculado en vez del centro fijo `(iw-cropw)/2`.

- [ ] **Step 1: Write the failing test**

```python
def test_detect_short_clips_uses_action_center_frac_in_crop_filter(tmp_path, monkeypatch):
    video = tmp_path / "mission.mp4"
    video.write_bytes(b"fake")
    monkeypatch.setattr(dcs_meta, "_get_video_duration", lambda *a: 300.0)
    monkeypatch.setattr(dcs_meta, "_detect_action_center_frac", lambda *a, **kw: 0.75)

    captured_cmds = []

    def fake_run(cmd, *a, **kw):
        captured_cmds.append(cmd)
        return _make_fake_process()

    monkeypatch.setattr("subprocess.run", fake_run)
    acmi = {"kills": [{"time_s": 60.0}], "sam_launches": [], "bvr_launches": [],
            "ejection_events": [], "guided_bomb_drops": []}

    dcs_meta.detect_short_clips(video, acmi, {})

    crop_cmds = [c for c in captured_cmds if "crop" in str(c)]
    assert crop_cmds, "No ffmpeg crop command was issued"
    vf_arg = crop_cmds[0][crop_cmds[0].index("-vf") + 1]
    assert "0.7500" in vf_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k action_center_frac_in_crop_filter -v --no-cov`
Expected: FAIL — el `-vf` actual no contiene `"0.7500"` (usa el offset fijo `(iw-ih*9/16)/2`).

- [ ] **Step 3: Write minimal implementation**

En `dcs_meta.py`, dentro de `detect_short_clips()`, sustituir el bloque del filtro `crop` fijo
(línea 1722):

```python
        output_path = shorts_dir / f"{video_path.stem}_short_{i + 1}.mp4"
        center_frac = _detect_action_center_frac(video_path, start, duration)
        crop_filter = (
            f"crop=ih*9/16:ih:"
            f"min(max(iw*{center_frac:.4f}-ih*9/32\\,0)\\,iw-ih*9/16):0,"
            "scale=1080:1920"
        )
        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(start),
                    "-i", str(video_path),
                    "-t", str(duration),
                    "-vf", crop_filter,
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac",
                    str(output_path),
                ],
                capture_output=True, check=True,
            )
```

(el resto del bloque `try`/`except` no cambia — solo se reemplaza el valor literal del argumento
`-vf` por la variable `crop_filter` calculada arriba).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k action_center_frac_in_crop_filter -v --no-cov`
Expected: PASS

- [ ] **Step 5: Run the full detect_short_clips test group to check no regressions**

Run: `.venv/bin/python -m pytest tests/test_dcs_meta.py -k "detect_short_clips or score_band_activity or detect_action_center_frac" -v --no-cov`
Expected: PASS — todos los tests existentes de `detect_short_clips` siguen en verde (cuando
`_detect_action_center_frac` no está mockeada, cae a `0.5` porque `subprocess.run` está mockeado a
un proceso falso que no escribe fichero real, así que `Image.open` falla y se activa el fallback —
matemáticamente equivalente al offset fijo anterior).

- [ ] **Step 6: Run full suite to check no regressions**

Run: `.venv/bin/python -m pytest --no-cov`
Expected: PASS (todos los tests del repo en verde)

- [ ] **Step 7: Commit**

```bash
git add dcs_meta.py tests/test_dcs_meta.py
git commit -m "feat(shorts-crop): usa el offset de _detect_action_center_frac en el crop de Shorts"
```

---

### Task 4: Documentación — cerrar BUG-01

**Files:**
- Modify: `BACKLOG.md` (eliminar la fila `BUG-01`, ya resuelta)
- Modify: `CHANGELOG.md`
- Modify: `SPEC.md` (marcar la sección como Implementada)

**Interfaces:** ninguna — cambios puramente documentales.

- [ ] **Step 1: Actualizar `BACKLOG.md`**

Eliminar la fila `BUG-01` de la tabla "Bugs" (ya resuelta). Si queda vacía, restaurar el texto
"Sin bugs confirmados..." que había antes.

- [ ] **Step 2: Añadir entrada en `CHANGELOG.md`**

Bajo `[No publicado] → Corregido` (crear la subsección si no existe todavía en `[No publicado]`),
anotar: el recorte 9:16 de Shorts ahora se desplaza hacia la zona de más detalle visual del frame
en vez de recortar siempre el centro fijo (BUG-01).

- [ ] **Step 3: Marcar la sección de `SPEC.md` como implementada**

Cambiar `**Estado:** Aprobada 2026-09-07` a `**Estado:** Implementada AAAA-MM-DD` (fecha real de
cierre) en la sección "Recorte 9:16 de Shorts centrado en la acción".

- [ ] **Step 4: Commit**

```bash
git add BACKLOG.md CHANGELOG.md SPEC.md
git commit -m "docs: cierra BUG-01 (recorte 9:16 de Shorts centrado en la acción)"
```

---

## Self-Review

**Cobertura del spec:** RF-1 → Task 1. RF-2 → Task 2. RF-3 (fallback a 0.5) → Task 2 Steps 1-3
(tests explícitos de `duration<=0` y de fallo total de muestreo). RF-4 (integración en el filtro
`crop`) → Task 3. RF-5 (resto del pipeline sin cambios) → verificado en Task 3 Step 5-6, ningún
test de selección de ventana/timestamp se toca.

**Placeholders:** ninguno pendiente.

**Consistencia de tipos:** `_score_band_activity(img, n_bands=8) -> list[float]` se usa igual en
Task 1 (definición) y Task 2 (uso real dentro de `_detect_action_center_frac`, y mockeada en el
test de Task 2 Step 1 con la misma firma `lambda img, n_bands=8: [...]`).
`_detect_action_center_frac(video_path, start, duration, n_samples=5, n_bands=8) -> float` se usa
igual en Task 2 (definición) y Task 3 (uso real y mock `lambda *a, **kw: 0.75`).
