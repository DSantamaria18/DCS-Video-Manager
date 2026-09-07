# Subida por lotes de YouTube Shorts — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar `POST /api/upload_shorts_batch`, que sube hasta 15 clips de YouTube Shorts ya
generados (`output/shorts/`) a YouTube en un solo lote, con publicación escalonada vía `publishAt`, y
cablear la UI (`uploadSelectedShorts()`) para dispararlo y mostrar progreso por clip.

**Architecture:** Nuevo endpoint Flask en `web/app.py` que valida el payload, crea un job en
`processing_status` y lanza un hilo (`_run_shorts_batch`) que sube cada clip secuencialmente con la
`youtube_uploader.upload_video()` ya existente (sin tocar ese módulo), calculando `publish_at` por
índice y sin abortar el lote ante un fallo individual. El frontend añade un panel de programación bajo
la grid de Shorts, bloquea la selección a 15 clips, y hace polling al mismo `job_id` para pintar el
estado de cada card.

**Tech Stack:** Python 3.10+, Flask, pytest + `unittest.mock.patch` (mismo patrón que
`tests/test_app.py`), JavaScript vanilla embebido en `web/templates/index.html` (sin build step, sin
framework de tests JS — verificación manual en navegador con `DCS_SIMULATE=1`).

## Global Constraints

- Máx. 15 clips por lote; se valida en backend (400) y se bloquea en UI (checkbox 16 deshabilitado).
- Los Shorts se suben siempre con `privacyStatus=private` + `publishAt` futuro — nunca públicos de
  inmediato (regla del proyecto: "ningún vídeo se publica sin revisión humana").
- Subida secuencial, nunca paralela.
- Un clip fallido no aborta el resto del lote; se registra su error y se sigue con el siguiente.
- No se modifica `youtube_uploader.py`: ya soporta `publish_at`, `playlist_ids`, `tags` y
  `DCS_SIMULATE=1`.
- El título final de cada clip = título del card (generado o editado) + sufijo `#N`, N = el número del
  sufijo `_short_N` del nombre de fichero del clip.
- La playlist SHORTS (detectada por título que contenga "short", case-insensitive) se añade siempre,
  sin necesidad de que el usuario la seleccione.
- Reutilizar patrones ya existentes en el repo: `processing_status`/`/api/status/<job_id>` para jobs
  async, `threading.Thread(daemon=True)`, mocks de `youtube_uploader.upload_video` en tests como en
  `tests/test_app.py`.

---

### Task 1: `_compute_publish_at` — cálculo de fecha escalonada

**Files:**
- Modify: `web/app.py` (añadir junto a los imports de `datetime` ya usados en el fichero, ~línea 995)
- Test: `tests/test_app.py`

**Interfaces:**
- Produces: `_compute_publish_at(first_publish_at: str, interval_days: int, order: int) -> str` — recibe
  un ISO 8601 con sufijo `Z` (formato que ya produce `Date.toISOString()` en el frontend, ver
  `uploadToYouTube()` en `index.html`), devuelve otro ISO 8601 con sufijo `Z` desplazado
  `interval_days * (order - 1)` días. `order` es 1-based.

- [ ] **Step 1: Write the failing test**

Añadir en `tests/test_app.py`, junto a otros tests de helpers puros (después del bloque de
`_suggest_playlist_ids`, ~línea 528):

```python
# ── _compute_publish_at ────────────────────────────────────────────────────────

def test_compute_publish_at_order_1_returns_first_date():
    from app import _compute_publish_at
    result = _compute_publish_at("2026-06-01T19:00:00Z", 3, 1)
    assert result == "2026-06-01T19:00:00Z"


def test_compute_publish_at_order_3_adds_interval_times_two():
    from app import _compute_publish_at
    result = _compute_publish_at("2026-06-01T19:00:00Z", 3, 3)
    assert result == "2026-06-07T19:00:00Z"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -k compute_publish_at -v`
Expected: FAIL — `ImportError: cannot import name '_compute_publish_at'`

- [ ] **Step 3: Write minimal implementation**

En `web/app.py`, junto al resto de imports de `datetime`/`timedelta` (ya se usan en el fichero, buscar
`from datetime import`; si el import actual es local a una función, añade uno a nivel de módulo si no
existe ya `timedelta`):

```python
def _compute_publish_at(first_publish_at: str, interval_days: int, order: int) -> str:
    """Return the ISO 8601 (Z-suffixed) publish_at for a clip at position `order` (1-based)."""
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(first_publish_at.replace("Z", "+00:00"))
    scheduled = base + timedelta(days=interval_days * (order - 1))
    return scheduled.strftime("%Y-%m-%dT%H:%M:%SZ")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -k compute_publish_at -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_app.py
git commit -m "feat(shorts-batch): añade _compute_publish_at para fechas escalonadas"
```

---

### Task 2: `_validate_shorts_batch` — validación del payload

**Files:**
- Modify: `web/app.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: nada de tareas anteriores.
- Produces: `_validate_shorts_batch(data: dict) -> str | None` — devuelve un mensaje de error (para
  responder 400) o `None` si el payload es válido. Payload esperado:
  `{"clips": [{"clip_path": str, "order": int, "title": str, "description": str, "tags": list}, ...],
  "first_publish_at": str, "interval_days": int, "playlist_ids": list (opcional)}`.

- [ ] **Step 1: Write the failing test**

```python
# ── _validate_shorts_batch ──────────────────────────────────────────────────────

def test_validate_shorts_batch_empty_clips_returns_error():
    from app import _validate_shorts_batch
    error = _validate_shorts_batch({"clips": [], "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None
    assert "clips" in error.lower()


def test_validate_shorts_batch_more_than_15_clips_returns_error():
    from app import _validate_shorts_batch
    clips = [{"clip_path": "/x.mp4", "order": i} for i in range(16)]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None
    assert "15" in error


def test_validate_shorts_batch_nonexistent_clip_path_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clips = [{"clip_path": str(tmp_path / "missing.mp4"), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 1})
    assert error is not None


def test_validate_shorts_batch_missing_first_publish_at_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "interval_days": 1})
    assert error is not None
    assert "first_publish_at" in error


def test_validate_shorts_batch_invalid_interval_days_returns_error(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 0})
    assert error is not None
    assert "interval_days" in error


def test_validate_shorts_batch_valid_payload_returns_none(tmp_path):
    from app import _validate_shorts_batch
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    clips = [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}]
    error = _validate_shorts_batch({"clips": clips, "first_publish_at": "2026-06-01T19:00:00Z",
                                     "interval_days": 3})
    assert error is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -k validate_shorts_batch -v`
Expected: FAIL — `ImportError: cannot import name '_validate_shorts_batch'`

- [ ] **Step 3: Write minimal implementation**

En `web/app.py`, justo debajo de `_compute_publish_at`:

```python
def _validate_shorts_batch(data: dict) -> str | None:
    """Return an error message if the shorts-batch payload is invalid, else None."""
    clips = data.get("clips") or []
    if not clips:
        return "Missing clips"
    if len(clips) > 15:
        return "Too many clips: max 15 per batch"
    for clip in clips:
        clip_path = clip.get("clip_path", "")
        if not clip_path or not Path(clip_path).exists():
            return f"Clip not found: {clip_path}"

    first_publish_at = data.get("first_publish_at", "")
    if not first_publish_at:
        return "Missing first_publish_at"
    try:
        _compute_publish_at(first_publish_at, 0, 1)
    except ValueError:
        return "Invalid first_publish_at"

    interval_days = data.get("interval_days")
    if not isinstance(interval_days, int) or interval_days < 1:
        return "interval_days must be an integer >= 1"

    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -k validate_shorts_batch -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_app.py
git commit -m "feat(shorts-batch): añade _validate_shorts_batch"
```

---

### Task 3: Endpoint `POST /api/upload_shorts_batch` — validación y creación del job

**Files:**
- Modify: `web/app.py` (nueva ruta, junto a `/api/generate_shorts`, ~línea 770)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `_validate_shorts_batch` (Task 2), `processing_status`, `_evict_old_jobs()` (ya existentes).
- Produces: ruta `/api/upload_shorts_batch`; en éxito, `processing_status[job_id]` con la forma
  `{"status": "uploading_batch", "message": str, "result": None, "error": None,
  "clips": {order: {"status": "pending"}, ...}}`. La función `_run_shorts_batch` (Task 4) es quien la
  actualiza después; en este task se referencia pero no se implementa todavía — usar un stub temporal
  que no haga nada (`lambda *a: None`) para poder testear la creación del job de forma aislada, y
  sustituirlo por la implementación real en el Task 4 (mismo nombre de función, misma firma).

- [ ] **Step 1: Write the failing test**

```python
# ── POST /api/upload_shorts_batch ───────────────────────────────────────────────

def test_upload_shorts_batch_invalid_payload_returns_400(client):
    resp = client.post("/api/upload_shorts_batch", json={"clips": []})
    assert resp.status_code == 400
    assert "error" in resp.json


def test_upload_shorts_batch_valid_payload_returns_job_id(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T",
                       "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
    assert resp.status_code == 200
    assert "job_id" in resp.json


def test_upload_shorts_batch_job_starts_with_pending_clips(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")
    with patch("app.threading.Thread") as mock_thread_cls:
        mock_thread_cls.return_value.start.return_value = None
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
    job_id = resp.json["job_id"]
    status = client.get(f"/api/status/{job_id}")
    assert status.json["status"] == "uploading_batch"
    assert status.json["clips"]["1"]["status"] == "pending"
    assert status.json["clips"]["2"]["status"] == "pending"
```

Nota: `processing_status[job_id]["clips"]` se indexa con `int` en Python pero `jsonify` lo serializa a
claves string en el JSON de respuesta — de ahí `status.json["clips"]["1"]` en el test (string), no `[1]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -k upload_shorts_batch -v`
Expected: FAIL — 404 (ruta no existe)

- [ ] **Step 3: Write minimal implementation**

En `web/app.py`, debajo de `serve_shorts_file` (~línea 770):

```python
@app.route("/api/upload_shorts_batch", methods=["POST"])
def upload_shorts_batch():
    """POST /api/upload_shorts_batch — upload up to 15 Shorts sequentially with staggered publish_at.

    Request body: {"clips": [{"clip_path": str, "order": int, "title": str,
    "description": str, "tags": list}], "first_publish_at": str (ISO 8601, Z-suffixed),
    "interval_days": int, "playlist_ids": list (optional, extra playlists — the SHORTS
    playlist is always added automatically)}.
    Starts a background job; poll /api/status/<job_id> — the response includes a "clips"
    dict keyed by order with each clip's upload status (pending/uploading/done/error).
    """
    data = request.get_json()
    error = _validate_shorts_batch(data)
    if error:
        return jsonify({"error": error}), 400

    clips = data["clips"]
    first_publish_at = data["first_publish_at"]
    interval_days = data["interval_days"]
    playlist_ids = data.get("playlist_ids") or []

    _evict_old_jobs()
    job_id = str(uuid.uuid4())[:8]
    processing_status[job_id] = {
        "status": "uploading_batch",
        "message": "Starting batch upload...",
        "result": None,
        "error": None,
        "clips": {clip["order"]: {"status": "pending"} for clip in clips},
    }

    thread = threading.Thread(
        target=_run_shorts_batch,
        args=(job_id, clips, first_publish_at, interval_days, playlist_ids),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


def _run_shorts_batch(job_id, clips, first_publish_at, interval_days, playlist_ids):
    """Placeholder — implemented in full in Task 4. Keeps Task 3's tests isolated
    (they patch threading.Thread, so this body never actually runs in those tests)."""
    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -k upload_shorts_batch -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add web/app.py tests/test_app.py
git commit -m "feat(shorts-batch): añade endpoint /api/upload_shorts_batch y creación del job"
```

---

### Task 4: `_run_shorts_batch` — orquestación real del hilo (subida secuencial, continue-on-error, playlist SHORTS)

**Files:**
- Modify: `web/app.py` (reemplaza el placeholder del Task 3)
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `youtube_uploader.get_playlists() -> list[dict]` (ya existe, cada dict trae `id`/`title`),
  `youtube_uploader.upload_video(...)` (ya existe, firma en `youtube_uploader.py:195`),
  `_compute_publish_at` (Task 1).
- Produces: `_run_shorts_batch(job_id, clips, first_publish_at, interval_days, playlist_ids)` —
  actualiza `processing_status[job_id]` in-place; al terminar dejar
  `status="done"`, `result={"uploaded": int, "failed": int}`, y cada
  `clips[order] = {"status": "done", "video_id": ..., "url": ...}` o
  `{"status": "error", "error": str}`.

- [ ] **Step 1: Write the failing test**

```python
# ── _run_shorts_batch (vía el endpoint, con Thread real y upload_video mockeado) ──

def test_run_shorts_batch_uploads_all_clips_in_order(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.get_playlists", return_value=[]), \
         patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 3,
        })
        job_id = resp.json["job_id"]

    # El hilo real corre en background; como upload_video está mockeado (rápido),
    # para el momento del assert ya debería haber terminado.
    import time
    for _ in range(50):
        if client.get(f"/api/status/{job_id}").json["status"] == "done":
            break
        time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["status"] == "done"
    assert status["clips"]["1"]["status"] == "done"
    assert status["clips"]["2"]["status"] == "done"
    assert status["result"] == {"uploaded": 2, "failed": 0}
    assert mock_uv.call_count == 2
    assert mock_uv.call_args_list[0].kwargs["publish_at"] == "2026-06-01T19:00:00Z"
    assert mock_uv.call_args_list[1].kwargs["publish_at"] == "2026-06-04T19:00:00Z"


def test_run_shorts_batch_continues_after_one_clip_fails(client, tmp_path):
    clip1 = tmp_path / "a_short_1.mp4"
    clip1.write_bytes(b"fake")
    clip2 = tmp_path / "a_short_2.mp4"
    clip2.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}

    with patch("youtube_uploader.get_playlists", return_value=[]), \
         patch("youtube_uploader.upload_video",
               side_effect=[Exception("quota exceeded"), upload_result]):
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [
                {"clip_path": str(clip1), "order": 1, "title": "T1", "description": "D", "tags": []},
                {"clip_path": str(clip2), "order": 2, "title": "T2", "description": "D", "tags": []},
            ],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
        })
        job_id = resp.json["job_id"]

    import time
    for _ in range(50):
        if client.get(f"/api/status/{job_id}").json["status"] == "done":
            break
        time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["clips"]["1"]["status"] == "error"
    assert "quota exceeded" in status["clips"]["1"]["error"]
    assert status["clips"]["2"]["status"] == "done"
    assert status["result"] == {"uploaded": 1, "failed": 1}


def test_run_shorts_batch_always_includes_shorts_playlist(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")

    upload_result = {"video_id": "X", "url": "https://youtu.be/X", "status": "uploaded",
                      "privacy": "private", "tags_skipped": False, "playlists_added": []}
    playlists = [{"id": "SH", "title": "SHORTS"}, {"id": "DW", "title": "DCS World"}]

    with patch("youtube_uploader.get_playlists", return_value=playlists), \
         patch("youtube_uploader.upload_video", return_value=upload_result) as mock_uv:
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
            "playlist_ids": ["PL_extra"],
        })
        job_id = resp.json["job_id"]

    import time
    for _ in range(50):
        if client.get(f"/api/status/{job_id}").json["status"] == "done":
            break
        time.sleep(0.05)

    mock_uv.assert_called_once()
    called_playlists = mock_uv.call_args.kwargs["playlist_ids"]
    assert "SH" in called_playlists
    assert "PL_extra" in called_playlists
    assert "DW" not in called_playlists


def test_run_shorts_batch_auth_failure_marks_all_clips_error(client, tmp_path):
    clip = tmp_path / "a_short_1.mp4"
    clip.write_bytes(b"fake")

    with patch("youtube_uploader.get_playlists", side_effect=PermissionError("Not authenticated")):
        resp = client.post("/api/upload_shorts_batch", json={
            "clips": [{"clip_path": str(clip), "order": 1, "title": "T", "description": "D", "tags": []}],
            "first_publish_at": "2026-06-01T19:00:00Z",
            "interval_days": 1,
        })
        job_id = resp.json["job_id"]

    import time
    for _ in range(50):
        if client.get(f"/api/status/{job_id}").json["status"] == "error":
            break
        time.sleep(0.05)

    status = client.get(f"/api/status/{job_id}").json
    assert status["status"] == "error"
    assert status["clips"]["1"]["status"] == "error"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_app.py -k run_shorts_batch -v`
Expected: FAIL — el placeholder no sube nada, los jobs se quedan en `uploading_batch`/`pending` para
siempre (timeout del loop de polling del test, o asserts sobre `status["result"]` fallando con `None`).

- [ ] **Step 3: Write minimal implementation**

Reemplaza el placeholder del Task 3 en `web/app.py`:

```python
def _run_shorts_batch(job_id, clips, first_publish_at, interval_days, playlist_ids):
    """Upload each clip sequentially via youtube_uploader.upload_video(); a single clip's
    failure does not abort the rest of the batch."""
    from youtube_uploader import get_playlists, upload_video

    try:
        playlists = get_playlists()
    except Exception as e:  # noqa: BLE001 — boundary: fallo de auth/listado no debe tumbar el hilo
        processing_status[job_id]["status"] = "error"
        processing_status[job_id]["error"] = str(e)
        for clip in clips:
            processing_status[job_id]["clips"][clip["order"]] = {"status": "error", "error": str(e)}
        return

    shorts_playlist_ids = [pl["id"] for pl in playlists if "short" in pl.get("title", "").lower()]
    all_playlist_ids = list(dict.fromkeys([*playlist_ids, *shorts_playlist_ids]))

    ordered_clips = sorted(clips, key=lambda c: c["order"])
    done_count = 0
    error_count = 0

    for clip in ordered_clips:
        order = clip["order"]
        processing_status[job_id]["clips"][order] = {"status": "uploading"}
        try:
            publish_at = _compute_publish_at(first_publish_at, interval_days, order)
            result = upload_video(
                video_path=clip["clip_path"],
                title=clip.get("title", ""),
                description=clip.get("description", ""),
                tags=clip.get("tags", []),
                privacy="private",
                playlist_ids=all_playlist_ids,
                publish_at=publish_at,
            )
            processing_status[job_id]["clips"][order] = {
                "status": "done",
                "video_id": result.get("video_id"),
                "url": result.get("url"),
            }
            done_count += 1
        except Exception as e:  # noqa: BLE001 — boundary: fallo de un clip no debe abortar el resto del lote
            processing_status[job_id]["clips"][order] = {"status": "error", "error": str(e)}
            error_count += 1

    processing_status[job_id]["status"] = "done"
    processing_status[job_id]["message"] = f"Done! {done_count} uploaded, {error_count} failed."
    processing_status[job_id]["result"] = {"uploaded": done_count, "failed": error_count}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_app.py -k "run_shorts_batch or upload_shorts_batch or validate_shorts_batch or compute_publish_at" -v`
Expected: PASS (todos los tests de las Tasks 1-4)

- [ ] **Step 5: Run full suite to check no regressions**

Run: `pytest --no-cov`
Expected: PASS (todos los tests existentes siguen en verde)

- [ ] **Step 6: Commit**

```bash
git add web/app.py tests/test_app.py
git commit -m "feat(shorts-batch): implementa _run_shorts_batch (subida secuencial, continue-on-error, playlist SHORTS)"
```

---

### Task 5: Frontend — panel de programación y wiring de `uploadSelectedShorts()`

**Files:**
- Modify: `web/templates/index.html`

**Interfaces:**
- Consumes: `POST /api/upload_shorts_batch` (Task 3/4), `GET /api/status/<job_id>` (ya existente),
  `showToast(msg, type)` (ya existente, ~línea 2117), `escHtml` (ya existente).
- Produces: función `uploadSelectedShorts()` real (sustituye el stub), función auxiliar
  `_shortClipOrder(clip)` que extrae el N de `_short_N.mp4` del `clip_path`.

- [ ] **Step 1: Añadir el panel de programación al HTML**

En `web/templates/index.html`, sustituir el bloque de `shortsGrid` (líneas 1034-1039):

```html
            <div id="shortsGrid" style="display:none;margin-top:10px">
              <div id="shortsCards" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;"></div>
              <div style="margin-top:14px;border-top:1px solid var(--border);padding-top:12px;">
                <div style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end;margin-bottom:10px;">
                  <label style="font-family:var(--mono);font-size:10px;color:var(--text3);">
                    FIRST PUBLISH<br>
                    <input type="datetime-local" id="shortsFirstPublishAt"
                      style="background:var(--bg3);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:2px;margin-top:3px;">
                  </label>
                  <label style="font-family:var(--mono);font-size:10px;color:var(--text3);">
                    INTERVAL (DAYS)<br>
                    <input type="number" id="shortsIntervalDays" value="3" min="1"
                      style="width:60px;background:var(--bg3);border:1px solid var(--border);color:var(--text);font-family:var(--mono);font-size:10px;padding:4px 6px;border-radius:2px;margin-top:3px;text-align:center;">
                  </label>
                </div>
                <div style="font-family:var(--mono);font-size:9px;color:var(--text3);margin-bottom:4px;">EXTRA PLAYLISTS (SHORTS playlist added automatically)</div>
                <div id="shortsPlaylistList" style="max-height:120px;overflow-y:auto;border:1px solid var(--border);border-radius:2px;margin-bottom:10px;"></div>
                <div style="display:flex;align-items:center;gap:10px;">
                  <button class="action-btn" id="shortsUploadBtn" onclick="uploadSelectedShorts()" style="background:var(--blue2);border-color:var(--blue);">PROGRAM BATCH</button>
                  <span id="shortsUploadMsg" style="font-family:var(--mono);font-size:10px;color:var(--text3)"></span>
                </div>
              </div>
            </div>
```

- [ ] **Step 2: Cargar playlists extra (excluyendo SHORTS) cuando se renderiza la grid**

En `renderShortsGrid()` (~línea 2005), al final de la función, justo antes de `grid.style.display = ...`,
añadir la llamada a una nueva función `loadShortsPlaylists()`:

```javascript
  grid.style.display = clips.length ? '' : 'none';
  grid.__clips = clips;
  if (clips.length) loadShortsPlaylists();
```

Añadir la función `loadShortsPlaylists()` junto a `loadPlaylists()` (~línea 2626), reutilizando el mismo
`fetch('/api/playlists')`:

```javascript
async function loadShortsPlaylists() {
  try {
    const res = await fetch('/api/playlists');
    const data = await res.json();
    const list = document.getElementById('shortsPlaylistList');
    if (!list || data.error) return;

    const playlists = (Array.isArray(data) ? data : (data.playlists || []))
      .filter(p => !(p.title || '').toLowerCase().includes('short'));
    list.innerHTML = '';
    playlists.forEach(p => {
      const row = document.createElement('label');
      row.style.cssText = 'display:flex;align-items:center;gap:8px;padding:5px 10px;cursor:pointer;font-family:var(--mono);font-size:11px;color:var(--text2);border-bottom:1px solid var(--border);';
      row.innerHTML = `<input type="checkbox" value="${p.id}" style="accent-color:var(--green);width:12px;height:12px;cursor:pointer;"><span>${escHtml(p.title)}</span>`;
      list.appendChild(row);
    });
  } catch(e) {}
}
```

- [ ] **Step 3: Extraer el orden del clip y construir el título con sufijo `#N`**

Añadir junto a `uploadSelectedShorts()` (~línea 2113):

```javascript
function _shortClipOrder(clip) {
  const m = /_short_(\d+)\.[^.]+$/.exec(clip.clip_path || '');
  return m ? parseInt(m[1], 10) : 0;
}
```

- [ ] **Step 4: Reemplazar el stub de `uploadSelectedShorts()` por la llamada real**

Sustituir el stub (líneas 2113-2115):

```javascript
async function uploadSelectedShorts() {
  const clips = (document.getElementById('shortsGrid').__clips) || [];
  const selected = [...document.querySelectorAll('#shortsCards input[type=checkbox]:checked')]
    .map(cb => clips[parseInt(cb.dataset.idx, 10)])
    .filter(Boolean);

  if (!selected.length) { showToast('Select at least one clip', 'error'); return; }
  if (selected.length > 15) { showToast('Max 15 clips per batch', 'error'); return; }

  const firstPublishRaw = document.getElementById('shortsFirstPublishAt').value;
  if (!firstPublishRaw) { showToast('Set the first publish date', 'error'); return; }
  const firstPublishAt = new Date(firstPublishRaw).toISOString();
  const intervalDays = parseInt(document.getElementById('shortsIntervalDays').value, 10) || 1;
  const extraPlaylistIds = [...document.querySelectorAll('#shortsPlaylistList input[type=checkbox]:checked')]
    .map(cb => cb.value);

  const payloadClips = selected.map(clip => {
    const order = _shortClipOrder(clip);
    const meta = clip.metadata || {};
    return {
      clip_path: clip.clip_path,
      order,
      title: `${meta.title || ''} #${order}`.trim(),
      description: meta.description || '',
      tags: meta.tags || [],
    };
  });

  const btn = document.getElementById('shortsUploadBtn');
  const msg = document.getElementById('shortsUploadMsg');
  btn.disabled = true;
  btn.textContent = 'Programming...';
  msg.textContent = `Uploading ${payloadClips.length} clip(s)...`;

  try {
    const res = await fetch('/api/upload_shorts_batch', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        clips: payloadClips,
        first_publish_at: firstPublishAt,
        interval_days: intervalDays,
        playlist_ids: extraPlaylistIds,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      showToast(data.error || 'Batch upload failed', 'error');
      btn.disabled = false;
      btn.textContent = 'PROGRAM BATCH';
      return;
    }
    pollShortsBatchJob(data.job_id, payloadClips.length);
  } catch (e) {
    showToast('Batch upload failed', 'error');
    btn.disabled = false;
    btn.textContent = 'PROGRAM BATCH';
  }
}
```

- [ ] **Step 5: Verificación manual en navegador**

```bash
DCS_SIMULATE=1 python web/app.py
```

Abrir `http://localhost:5000`, analizar un vídeo de prueba, generar Shorts, seleccionar 1-2 clips,
fijar fecha y pulsar "PROGRAM BATCH". Confirmar en la consola del navegador (Network tab) que
`/api/upload_shorts_batch` recibe el payload esperado y devuelve `job_id`. (El polling completo se
verifica en el Task 6, todavía no está cableado `pollShortsBatchJob`.)

- [ ] **Step 6: Commit**

```bash
git add web/templates/index.html
git commit -m "feat(shorts-batch): panel de programación y llamada real a upload_shorts_batch"
```

---

### Task 6: Frontend — bloqueo duro a 15 clips seleccionados

**Files:**
- Modify: `web/templates/index.html`

**Interfaces:**
- Consumes: los checkboxes `#shortsCards input[type=checkbox]` creados en `renderShortsGrid()` (Task 5
  ya existente, sin cambios de forma).
- Produces: función `_enforceShortsSelectionLimit()`.

- [ ] **Step 1: Añadir el listener de bloqueo tras renderizar la grid**

En `renderShortsGrid()`, después de `cards.appendChild(card);` dentro del `forEach` no hace falta tocar
nada; el listener se añade una vez, al final de `renderShortsGrid()`, junto a la llamada a
`loadShortsPlaylists()`:

```javascript
  grid.style.display = clips.length ? '' : 'none';
  grid.__clips = clips;
  if (clips.length) { loadShortsPlaylists(); _enforceShortsSelectionLimit(); }
```

- [ ] **Step 2: Implementar `_enforceShortsSelectionLimit()`**

Junto a `_shortClipOrder()`:

```javascript
function _enforceShortsSelectionLimit() {
  const boxes = [...document.querySelectorAll('#shortsCards input[type=checkbox]')];
  const update = () => {
    const checkedCount = boxes.filter(b => b.checked).length;
    boxes.forEach(b => { b.disabled = !b.checked && checkedCount >= 15; });
  };
  boxes.forEach(b => b.addEventListener('change', update));
  update();
}
```

- [ ] **Step 3: Verificación manual en navegador**

Con `DCS_SIMULATE=1 python web/app.py` corriendo, generar Shorts sobre un vídeo con más de 15 clips
detectados (o simular marcando manualmente 15 vía devtools si no hay tantos clips reales) y confirmar
que el checkbox 16 aparece deshabilitado, y que se reactiva al desmarcar uno.

- [ ] **Step 4: Commit**

```bash
git add web/templates/index.html
git commit -m "feat(shorts-batch): bloquea la selección de Shorts a 15 clips por lote"
```

---

### Task 7: Frontend — estado por card y toast resumen (polling)

**Files:**
- Modify: `web/templates/index.html`

**Interfaces:**
- Consumes: `GET /api/status/<job_id>` con la forma `{"status": "uploading_batch"|"done"|"error",
  "clips": {"<order>": {"status": "pending"|"uploading"|"done"|"error", "video_id"?, "url"?, "error"?}},
  "result": {"uploaded": int, "failed": int} | null}` (Task 3/4).
- Produces: `pollShortsBatchJob(jobId, totalClips)` (invocada desde `uploadSelectedShorts()`, Task 5).

- [ ] **Step 1: Añadir un badge de estado a cada card**

En `renderShortsGrid()`, dentro del `card.innerHTML`, añadir un `<span>` de estado justo debajo del
bloque de checkbox/título (después del `</label>`, antes del `<div>` de botones COPY META/DOWNLOAD/EDIT):

```html
      <div id="short_status_${idx}" style="font-family:var(--mono);font-size:9px;color:var(--text3);margin-top:6px;"></div>
```

Y en el `card.innerHTML` guardar el `order` como `data-order` en el checkbox para poder mapear
`order -> idx` al pintar el estado:

```html
        <input type="checkbox" id="${checkId}" data-idx="${idx}" data-order="${_shortClipOrder(clip)}"
```

(sustituye la línea del checkbox existente, que hoy solo tiene `data-idx`).

- [ ] **Step 2: Implementar `pollShortsBatchJob`**

Junto a `pollShortsJob()` (~línea 1974), añadir:

```javascript
let _shortsBatchInterval = null;

function pollShortsBatchJob(jobId, totalClips) {
  if (_shortsBatchInterval) clearInterval(_shortsBatchInterval);

  const orderToIdx = {};
  document.querySelectorAll('#shortsCards input[type=checkbox][data-order]').forEach(cb => {
    orderToIdx[cb.dataset.order] = cb.dataset.idx;
  });

  const badgeText = (c) => {
    if (c.status === 'done') return `✓ uploaded${c.url ? ' — ' + c.url : ''}`;
    if (c.status === 'error') return `✗ ${c.error || 'failed'}`;
    if (c.status === 'uploading') return '⟳ uploading...';
    return 'pending';
  };
  const badgeColor = (c) => c.status === 'done' ? 'var(--green)'
    : c.status === 'error' ? 'var(--red)' : 'var(--text3)';

  _shortsBatchInterval = setInterval(async () => {
    try {
      const res = await fetch('/api/status/' + jobId);
      const data = await res.json();
      const clips = data.clips || {};

      Object.entries(clips).forEach(([order, c]) => {
        const idx = orderToIdx[order];
        if (idx === undefined) return;
        const el = document.getElementById('short_status_' + idx);
        if (el) { el.textContent = badgeText(c); el.style.color = badgeColor(c); }
      });

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(_shortsBatchInterval);
        _shortsBatchInterval = null;
        const btn = document.getElementById('shortsUploadBtn');
        const msg = document.getElementById('shortsUploadMsg');
        btn.disabled = false;
        btn.textContent = 'PROGRAM BATCH';
        if (data.status === 'error') {
          msg.textContent = data.error || 'Batch failed';
          showToast(data.error || 'Batch upload failed', 'error');
        } else {
          const r = data.result || {};
          msg.textContent = `${r.uploaded || 0}/${totalClips} uploaded, ${r.failed || 0} failed`;
          showToast(`${r.uploaded || 0}/${totalClips} Shorts programmed. ${r.failed || 0} failed.`);
        }
      }
    } catch (e) {}
  }, 2000);
}
```

- [ ] **Step 3: Verificación manual en navegador**

Con `DCS_SIMULATE=1 python web/app.py` corriendo, repetir el flujo de generar/seleccionar/programar
Shorts y confirmar que cada card pasa de "pending" a "✓ uploaded" y que aparece el toast resumen final.

- [ ] **Step 4: Commit**

```bash
git add web/templates/index.html
git commit -m "feat(shorts-batch): pinta estado por card y toast resumen del lote"
```

---

### Task 8: Documentación — cerrar FEA-06

**Files:**
- Modify: `BACKLOG.md` (mover FEA-06 de "Features propuestas" a implementado)
- Modify: `CHANGELOG.md`
- Modify: `SPEC.md` (marcar la sección como Implementada)

**Interfaces:** ninguna — cambios puramente documentales.

- [ ] **Step 1: Actualizar `BACKLOG.md`**

Eliminar la fila `FEA-06` de la tabla "Features propuestas" (ya no está propuesta, está implementada).

- [ ] **Step 2: Añadir entrada en `CHANGELOG.md`**

Seguir el formato ya usado en el fichero (ver entradas de FEA-02/FEA-04) para anotar: nuevo endpoint
`/api/upload_shorts_batch`, subida por lotes de hasta 15 Shorts con publicación escalonada.

- [ ] **Step 3: Marcar la sección de `SPEC.md` como implementada**

Cambiar `**Estado:** Aprobada 2026-09-07` a `**Estado:** Implementada AAAA-MM-DD` (fecha real de cierre).

- [ ] **Step 4: Commit**

```bash
git add BACKLOG.md CHANGELOG.md SPEC.md
git commit -m "docs: cierra FEA-06 (subida por lotes de YouTube Shorts)"
```

---

## Self-Review

**Cobertura del spec:** RF-1/RF-2/RF-3 → Task 5/6 (UI). RF-4 (sufijo `#N`) → Task 5 Step 3-4. RF-5 →
Task 5 Step 4. RF-6 (validación 400) → Task 2/3. RF-7 (subida secuencial + `publish_at` escalonado) →
Task 1/4. RF-8 (continue-on-error) → Task 4. RF-9 (`processing_status` por clip + polling) → Task
3/4/7. RF-10 (toast resumen) → Task 7. RF-11 (`DCS_SIMULATE`) → cubierto gratis por
`youtube_uploader.upload_video()`, no requiere código nuevo (verificado en Task 5/6/7 Step de
verificación manual, que corre con `DCS_SIMULATE=1`).

**Placeholders:** ninguno pendiente — el único "placeholder" intencional es la función stub del Task 3
Step 3, explícitamente sustituida en el Task 4 Step 3 (mismo nombre y firma, documentado en la
interfaz de ambos tasks).

**Consistencia de tipos:** `_compute_publish_at(first_publish_at: str, interval_days: int, order: int) -> str`
se usa igual en Task 1 (definición), Task 2 (validación, con `order=1` fijo para probar el parseo) y
Task 4 (uso real). `clip["order"]`/`clip["clip_path"]`/`clip.get("title"/"description"/"tags")` son
consistentes entre el payload de Task 3, la implementación de Task 4 y la construcción del payload en
el frontend (Task 5 Step 4).
