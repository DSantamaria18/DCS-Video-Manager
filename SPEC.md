# SPEC.md — DCS Video Manager

Documento de especificaciones. **La regla 2 de `CLAUDE.md` exige que se redacte conjuntamente con David
y que él lo apruebe explícitamente antes de escribir código.** Por eso este fichero es una plantilla con
las secciones a rellenar, no un documento ya escrito por un agente.

**Estado: BORRADOR — sin aprobar.**

---

## Cómo se usa

- Se abre una sección `## Feature: <nombre>` por cada desarrollo nuevo.
- El Tech Lead la redacta con David, incluyendo preguntas abiertas.
- Nadie escribe código hasta que David apruebe explícitamente esa sección.
- Aprobada la especificación, el Tech Lead la divide en tareas y presenta el plan detallado (regla 3).
  El plan también necesita luz verde explícita antes de tocar código.
- Cuando la feature se implementa, la sección se conserva aquí como referencia histórica y el resultado
  se registra en `CHANGELOG.md` y `FEATURES.md`.

---

## Plantilla por feature

```markdown
## Feature: <nombre>

**Estado:** Borrador | Aprobada AAAA-MM-DD | Implementada AAAA-MM-DD | Descartada
**Entrada de BACKLOG.md:** <id>

### Problema
Qué duele hoy y a quién. Sin solución todavía.

### Objetivo
Qué debe ser cierto cuando esto esté hecho.

### Fuera de alcance
Qué NO se hace en esta iteración, para evitar que crezca sola.

### Requisitos funcionales
Numerados y verificables (RF-1, RF-2...). Cada uno debe poder convertirse en un test.

### Requisitos no funcionales
Rendimiento, coste de API, comportamiento sin conexión, límites de cuota, compatibilidad de SO.
Los define QA junto al Tech Lead.

### Contratos afectados
Endpoints nuevos o modificados, forma del payload de entrada y de salida, cambios en el esquema de
config.json o de history.json. Marca explícitamente si algo cruza la frontera servidor ↔ navegador:
eso obliga a verificación en navegador real.

### Impacto en ficheros
Qué módulos se tocan. Sirve para decidir si la feature es separable entre los 2 Developers o debe ir
a uno solo.

### Dependencias externas
Paquetes nuevos (verificados contra documentación oficial), credenciales necesarias, cuotas de API.
Las credenciales se piden ANTES de despachar a QA.

### Quality gates
Cobertura mínima, linting, tests de seguridad aplicables. Los define QA.

### Riesgos y decisiones abiertas
Qué puede salir mal y qué preguntas quedan para David.

### Criterios de aceptación
Lista comprobable. Es lo que QA valida antes de que el Tech Lead haga el review.
```

---

## Feature: Subida por lotes de YouTube Shorts

**Estado:** Implementada 2026-09-07
**Entrada de BACKLOG.md:** FEA-06

### Problema
El botón "UPLOAD SELECTED" de la sección Shorts (`web/templates/index.html`, `uploadSelectedShorts()`)
no está implementado: solo muestra un aviso de subir manualmente en YouTube Studio. No existe backend
que suba los clips generados en `output/shorts/`.

### Objetivo
Poder seleccionar hasta 15 Shorts generados, programar su publicación escalonada (primera fecha/hora +
intervalo en días) y que la app los suba todos de una vez a YouTube, dejando que YouTube publique cada
uno en su fecha. Sin pasos manuales en YouTube Studio salvo revisar lo ya programado.

### Fuera de alcance
- Subida real distribuida en el tiempo (la app no necesita seguir corriendo días después: se sube todo
  ya, con `publishAt` escalonado — ver Riesgos y decisiones abiertas).
- Reordenar clips a mano en la UI: el orden lo fija el sufijo numérico del nombre de fichero
  (`_short_1`, `_short_2`...).
- Subida de más de 15 clips en una sola operación.
- Miniatura personalizada para Shorts (YouTube no la usa igual que en vídeo largo).

### Requisitos funcionales
- RF-1: Cada card de Short permite marcar/desmarcar un checkbox de selección; al llegar a 15
  marcados, el resto de checkboxes se deshabilita (bloqueo duro).
- RF-2: Un panel bajo "UPLOAD SELECTED" (renombrado a "PROGRAM BATCH") permite fijar fecha/hora de la
  primera publicación (`datetime-local`) y el intervalo en días (entero ≥ 1) entre publicaciones.
- RF-3: El selector de playlists ya existente se reutiliza para playlists "extra"; la playlist SHORTS
  (detectada por título, misma lógica que `_suggest_playlist_ids`) se añade siempre automáticamente,
  sin aparecer en la lista de selección para evitar duplicados.
- RF-4: El título final de cada clip subido = título del card (generado por `generate_short_metadata`
  o editado a mano) + sufijo `#N`, siendo N el índice del sufijo `_short_N` del nombre de fichero.
- RF-5: Al pulsar "PROGRAM BATCH", el frontend construye la lista ordenada por ese índice y llama una
  única vez a `POST /api/upload_shorts_batch`.
- RF-6: El backend valida el payload (clips no vacío, ≤ 15, cada `clip_path` existe, `first_publish_at`
  parseable, `interval_days` ≥ 1) devolviendo 400 si falla, antes de crear ningún job.
- RF-7: El backend crea un job y lanza un hilo que sube cada clip secuencialmente con
  `youtube_uploader.upload_video()`, calculando `publish_at = first_publish_at + interval_days*(orden-1)`.
- RF-8: Si un clip falla (excepción de `upload_video`), el job continúa con el resto; el error se
  guarda por clip y no aborta el lote.
- RF-9: `processing_status[job_id]['clips'][orden]` refleja el estado de cada clip
  (`pending`/`uploading`/`done`/`error`) para que el frontend lo pinte por card vía polling a
  `/api/status/<job_id>` (mismo mecanismo que el resto de jobs).
- RF-10: Al terminar el lote (con o sin errores parciales), el job pasa a `done` y el frontend muestra
  un toast resumen ("X/Y Shorts programados. Z fallidos.").
- RF-11: Con `DCS_SIMULATE=1`, cada clip usa la ruta simulada ya existente en `upload_video()` — sin
  llamadas reales a la API.

### Requisitos no funcionales
- Coste de API: cada clip del lote consume una unidad de cuota de subida de YouTube igual que el vídeo
  largo (hasta 15 por lote); sin llamadas nuevas a Gemini.
- Subida secuencial (no paralela) para no saturar la cuota ni complicar el manejo de progreso.
- Consistente con "ningún vídeo se publica sin revisión humana": los Shorts se suben siempre con
  `privacyStatus=private` + `publishAt` futuro (mismo comportamiento que ya fuerza `upload_video()` al
  recibir `publish_at`), nunca públicos de inmediato.

### Contratos afectados
- Nuevo endpoint `POST /api/upload_shorts_batch`. Payload:
  ```json
  {
    "clips": [
      {"clip_path": "output/shorts/x_short_1.mp4", "order": 1,
       "title": "...", "description": "...", "tags": ["..."]}
    ],
    "first_publish_at": "2026-06-01T19:00:00Z",
    "interval_days": 3,
    "playlist_ids": ["PL_extra1"]
  }
  ```
  Respuesta: `202 {"job_id": "..."}` o `400 {"error": "..."}` en validación. `401` con
  `"Not authenticated"` si no hay token OAuth (mismo patrón que `/api/upload_youtube`).
- `GET /api/status/<job_id>` ya existente amplía su forma de respuesta para este tipo de job con una
  clave `clips` (dict por orden). No cambia el contrato para jobs que no son de este tipo.
- No se modifica `youtube_uploader.upload_video()`: ya soporta `publish_at`, `playlist_ids`, `tags` y
  `DCS_SIMULATE`.

### Impacto en ficheros
- `web/app.py`: nuevo endpoint `/api/upload_shorts_batch`, función de orquestación del hilo, cálculo de
  `publish_at` por índice, extensión de `processing_status`.
- `web/templates/index.html`: panel de programación (fecha + intervalo + playlists extra), bloqueo de
  checkboxes a 15, cambio de `uploadSelectedShorts()` de stub a llamada real, badges de estado por card,
  toast resumen.
- Sin cambios en `youtube_uploader.py`, `dcs_meta.py` ni `discord_bot.py`.

### Dependencias externas
Ninguna nueva. Reutiliza YouTube Data API v3 (ya integrada) y OAuth2 ya configurado.

### Quality gates
- Cobertura de tests para el endpoint nuevo y la función de orquestación (sin umbral bloqueante, igual
  que el resto del repo — ver pregunta 3 de este documento).
- `ruff` sin errores nuevos.

### Riesgos y decisiones abiertas
- El límite de 15 clips por lote es una convención propia de David (evitar lotes descontrolados), no un
  límite documentado de la API de YouTube — se aplica como validación de la app, no como workaround de
  cuota.
- Como todos los clips se suben ya (hoy), y solo `publishAt` queda en el futuro, no hace falta ningún
  scheduler/cron que siga vivo: la app puede cerrarse tras completar el lote.

### Criterios de aceptación
- Seleccionar 15 clips habilita el bloqueo del checkbox 16.
- Programar un lote con fecha futura e intervalo de N días sube los clips con `DCS_SIMULATE=1` y cada
  uno recibe el `publish_at` correcto según su orden.
- Forzar el fallo de un clip (mock de `upload_video` lanzando excepción) no interrumpe la subida del
  resto; el resumen final refleja el fallo.
- La playlist SHORTS aparece en `playlists_added` de cada clip aunque no se seleccione ninguna playlist
  extra.
- El título subido de cada clip termina en `#N` con el N correcto.

---

## Feature: Recorte 9:16 de Shorts centrado en la acción

**Estado:** Implementada 2026-09-07
**Entrada de BACKLOG.md:** BUG-01

### Problema
`detect_short_clips()` (`dcs_meta.py:1722`) recorta siempre la franja horizontal central del
frame (`crop=ih*9/16:ih:(iw-ih*9/16)/2:0`). En DCS la cámara externa o el HUD suelen dejar el
avión/objetivo descentrado, así que el recorte fijo corta la parte relevante de la toma.

### Objetivo
Que el recorte 9:16 de cada Short se desplace horizontalmente hacia la zona del frame con más
detalle/actividad visual, en vez de recortar siempre el centro geométrico.

### Fuera de alcance
- Recorte dinámico que siga la acción moviéndose dentro del propio clip (paneo). Un único offset
  fijo por clip, calculado sobre varios frames de muestra.
- Cualquier llamada a Gemini u otra API externa para detectar el sujeto: la heurística es local
  (ffmpeg + Pillow), sin coste de cuota.
- Cambiar la resolución de salida (sigue siendo 1080x1920) o el criterio de selección de la
  ventana/timestamp del clip (eso ya lo resuelve `_collect_candidate_timestamps` y no se toca).

### Requisitos funcionales
- RF-1: `_score_band_activity(img, n_bands=8) -> list[float]` divide una imagen PIL en
  `n_bands` franjas verticales iguales y devuelve la puntuación de detalle/bordes de cada una
  (escala de grises + `ImageFilter.FIND_EDGES` + `ImageStat.Stat(...).mean[0]`, misma técnica
  que `thumbnail._score_frame`, implementada de forma independiente en `dcs_meta.py` para no
  acoplar los dos módulos).
- RF-2: `_detect_action_center_frac(video_path, start, duration, n_samples=5, n_bands=8) -> float`
  extrae `n_samples` frames equiespaciados dentro de `[start, start+duration]` (mismo patrón
  `ffmpeg -ss/-vframes 1` que `extract_frames()`), sirve cada uno a `_score_band_activity`,
  suma las puntuaciones por franja a través de las muestras, y devuelve `(banda_ganadora + 0.5) / n_bands`
  como fracción horizontal (0.0-1.0) del ancho del frame.
- RF-3: `_detect_action_center_frac` devuelve `0.5` (centro, comportamiento actual) si
  `duration <= 0` o si **todas** las extracciones de frames fallan (ffmpeg no instalado, error de
  proceso, fichero corrupto). No debe lanzar excepción hacia el llamador.
- RF-4: `detect_short_clips()` llama a `_detect_action_center_frac()` para cada clip antes de
  invocar ffmpeg, y construye el filtro `crop` con ese offset en vez del fijo `(iw-cropw)/2`:
  `crop=ih*9/16:ih:min(max(iw*{center_frac}-ih*9/32\,0)\,iw-ih*9/16):0,scale=1080:1920`.
- RF-5: El resto del pipeline de `detect_short_clips()` (selección de ventana, timestamp,
  duración, nombre de fichero) no cambia.

### Requisitos no funcionales
- Coste de API: cero — solo `ffmpeg` local (ya es una dependencia del sistema) y `Pillow` (ya en
  `requirements.txt`). Sin llamadas nuevas a Gemini.
- Rendimiento: 5 extracciones de frame adicionales por clip (imágenes pequeñas, `scale=640:-1`),
  overhead menor comparado con la propia extracción del clip de hasta 60s.
- Debe degradar con gracia: un fallo en el análisis de offset nunca debe impedir que el Short se
  genere (cae a recorte centrado, RF-3).

### Contratos afectados
Ninguno externo. Cambia la implementación interna de `detect_short_clips()` en `dcs_meta.py`; la
forma del resultado (`clip_path`, `hook`, `score`, etc.) no cambia, así que no afecta a
`/api/generate_shorts` ni al frontend.

### Impacto en ficheros
- `dcs_meta.py`: nuevas funciones `_score_band_activity` y `_detect_action_center_frac`, y el
  filtro `crop` de `detect_short_clips()` pasa a usar el offset calculado.
- Sin cambios en `thumbnail.py`, `web/app.py` ni `web/templates/index.html`.

### Dependencias externas
Ninguna nueva. Reutiliza `ffmpeg` (subprocess) y `Pillow` (ya instalados).

### Quality gates
- Cobertura de tests para ambas funciones nuevas (sin umbral bloqueante, igual que el resto del
  repo).
- `ruff` sin errores nuevos.

### Riesgos y decisiones abiertas
- La heurística de bordes puede fallar en escenas con poco contraste (cielo despejado, noche sin
  HUD visible) y devolver una banda poco significativa; el impacto es acotado porque en el peor
  caso el resultado es un recorte descentrado pero nunca peor que el comportamiento actual (que ya
  es un recorte fijo sin criterio).
- No se añade detección de "sujeto" real (avión, HUD): es una aproximación por concentración de
  detalle visual, no por reconocimiento de objetos. Si en la práctica no da buenos resultados, la
  alternativa con Gemini Vision queda anotada como camino futuro (con coste de cuota).

### Criterios de aceptación
- `_score_band_activity` sobre una imagen sintética con detalle concentrado en una franja
  identifica esa franja como la de mayor puntuación.
- `_detect_action_center_frac` devuelve `0.5` cuando `duration <= 0`.
- `_detect_action_center_frac` devuelve `0.5` cuando todas las llamadas a ffmpeg fallan (mockeadas).
- `_detect_action_center_frac` devuelve el centro de la banda ganadora cuando las muestras tienen
  éxito (mockeando `subprocess.run` y `PIL.Image.open` con puntuaciones controladas).
- `detect_short_clips()` pasa el `center_frac` calculado (mockeando `_detect_action_center_frac`)
  al argumento `-vf` de la llamada a ffmpeg.

---

## Feature: Estimación de coste antes de analizar

**Estado:** Implementada 2026-09-07
**Entrada de BACKLOG.md:** FEA-03

### Problema
La UI no indica cuántas llamadas a Gemini va a disparar una acción, ni cuántos frames/imágenes
manda cada una. David decide sin esa información, especialmente relevante con
`gemini-2.5-pro` (más caro por imagen que el `gemini-2.5-flash` por defecto).

### Objetivo
Que cada botón que llama a Gemini muestre, antes de pulsarlo, cuántos frames va a mandar y con
qué modelo, sin necesidad de ir a la pestaña Setup a comprobarlo.

### Fuera de alcance
- Contador de cuota diaria acumulada (llamadas ya hechas hoy / límite). Solo se muestra el coste
  de la próxima llamada, no un histórico. Ver Riesgos y decisiones abiertas.
- Detectar si el vídeo ya está cacheado (`get_cached_metadata`) para avisar de que ANALYZE VIDEO
  costaría 0 llamadas esa vez concreta — el badge asume siempre el caso "sin caché".
- Cualquier cambio de comportamiento en las llamadas a Gemini existentes (número de frames,
  modelo, prompts). Solo se muestra información ya determinada por la config actual.

### Requisitos funcionales
- RF-1: Se identifican los 4 botones que llaman a Gemini y su coste en frames, todos
  deterministas a partir de `cfg.frames_to_extract` (no dependen del contenido del vídeo):
  - ANALYZE VIDEO (`startAnalysis`) → `cfg.frames_to_extract` frames.
  - GENERATE DEBRIEF (`generateDebrief`) → `min(5, cfg.frames_to_extract)` frames.
  - GENERATE CAPTIONS (`generateSocialCaptions`) → 0 frames (solo texto).
  - FIX WITH AI / SEO (`rewriteWithAI`) → 0 frames (solo texto).
- RF-2: Cada uno de los 4 botones muestra junto a sí un badge de texto con el formato
  `"{N} frame(s) · {modelo}"` cuando N > 0, o `"Text only · {modelo}"` cuando N == 0.
- RF-3: El frontend mantiene un config cacheado (`_appConfig`), obtenido con un único
  `fetch('/api/config')` al cargar la página (`DOMContentLoaded`), reutilizado por los 4 badges
  en vez de repetir la llamada por cada uno.
- RF-4: Los badges se recalculan y repintan tras guardar cambios en la pestaña Setup
  (`saveConfig()` con éxito), para reflejar un `frames_to_extract` o `model` nuevos sin recargar
  la página.
- RF-5: GENERATE THUMBNAIL y GENERATE SHORTS no llevan badge — no llaman a Gemini (son locales,
  ffmpeg/Pillow).

### Requisitos no funcionales
- Cero llamadas nuevas a Gemini ni a ningún endpoint nuevo: el único fetch añadido es la carga
  inicial de `/api/config`, que ya existe como endpoint y ya se llama hoy desde `loadConfigForm()`
  (se cachea para no duplicar la petición).

### Contratos afectados
Ninguno. No se toca `web/app.py` ni `dcs_meta.py`; el cambio es exclusivamente frontend
(`web/templates/index.html`).

### Impacto en ficheros
- `web/templates/index.html`: variable global `_appConfig`, función `loadAppConfigBadges()`,
  4 elementos `<span>` de badge junto a los botones existentes, llamada a
  `loadAppConfigBadges()` en `DOMContentLoaded` y al final de `saveConfig()`.

### Dependencias externas
Ninguna.

### Quality gates
- Sin tests automatizados de JS en este repo (no hay framework, ver `CLAUDE.md`); verificación
  manual en navegador con `DCS_SIMULATE=1`: cambiar `frames_to_extract`/`model` en Setup, guardar,
  y comprobar que los 4 badges se actualizan sin recargar la página.

### Riesgos y decisiones abiertas
- El badge de ANALYZE VIDEO no distingue el caso cacheado (0 llamadas reales); queda anotado como
  posible mejora futura si en la práctica resulta confuso, pero no bloquea esta iteración (fuera
  de alcance explícito).
- Si en el futuro se añade un quinto botón que llame a Gemini, hay que añadir su badge a mano —
  no hay un registro central de "acciones que llaman a Gemini" que lo generalice. Aceptable dado
  el tamaño actual de la UI (YAGNI); revisar si la lista crece.

### Criterios de aceptación
- Con `DCS_SIMULATE=1`, cargar la página y ver los 4 badges con el frame count y modelo
  correctos según el config por defecto.
- Cambiar `frames_to_extract` a un valor distinto en Setup, guardar, y ver los badges de ANALYZE
  VIDEO y GENERATE DEBRIEF actualizados sin recargar la página (respetando el tope de 5 en
  DEBRIEF).
- Cambiar el modelo en Setup, guardar, y ver los 4 badges con el nuevo nombre de modelo.
- GENERATE CAPTIONS y FIX WITH AI muestran "Text only · {modelo}" siempre, sin depender de
  `frames_to_extract`.

---

## Feature: Cola de vídeos pendientes de publicar

**Estado:** Implementada 2026-10-18 (aprobada el mismo día con las 5 propuestas de las preguntas abiertas, resueltas abajo)
**Entrada de BACKLOG.md:** FEA-08

### Problema
Los vídeos largos ya subidos al canal como privados y sin fecha (`private`, sin `publishAt`) solo se pueden
programar a mano, uno a uno, en YouTube Studio. La cadencia escalonada (primera fecha + intervalo en días)
solo existe hoy para Shorts recién generados, no para lo que ya está en el canal.

### Objetivo
Ver en la app la lista de vídeos del canal pendientes de publicar, seleccionar los que se quieran, fijar
primera fecha/hora e intervalo en días, y que la app asigne a cada uno su `publishAt` en YouTube con el
mismo reparto que ya usan los Shorts (`_compute_publish_at`).

### Fuera de alcance
- Hacer públicos vídeos de inmediato (la app solo programa; el estado sigue siendo `private` hasta `publishAt`).
- Reprogramar vídeos que ya tienen `publishAt` (ver pregunta abierta 2).
- Editar título, descripción, tags o miniatura desde esta lista.
- Scheduler propio: la publicación la ejecuta YouTube, como ya decide `DECISIONS.md` ("Subida siempre como `private`, con `publishAt` opcional").
- Subir vídeos nuevos (ya lo cubre `/api/upload_youtube`).

### Requisitos funcionales
- RF-1: Un endpoint lista los vídeos del canal con `privacyStatus == "private"` y sin `publishAt`, ordenados
  por fecha de subida ascendente, con `video_id`, título, fecha de subida, duración, miniatura y una
  marca `is_short` (duración ≤ 3 min, heurística de etiqueta, no criterio de YouTube). El mismo endpoint
  devuelve aparte los vídeos con `publishAt` futuro, solo para mostrarlos.
- RF-2: La UI muestra esa lista con un checkbox por vídeo, tope de 15 seleccionados (mismo bloqueo duro
  que los Shorts) y un botón de recarga.
- RF-3: Un panel reutiliza los controles de los Shorts: primera publicación (`datetime-local`) e intervalo
  en días (entero ≥ 1).
- RF-4: Antes de enviar, la UI muestra la tabla vídeo → fecha calculada, y solo envía tras pulsar el botón
  de confirmación (regla 12 de `CLAUDE.md`: un disparo, una confirmación).
- RF-5: Un segundo endpoint valida el payload (lista no vacía, ≤ 15, `first_publish_at` parseable,
  `interval_days` ≥ 1, `video_id` sin repetir) y devuelve 400 antes de crear el job.
- RF-6: El orden de publicación es el orden de la lista (fecha de subida ascendente), con
  `publish_at = first_publish_at + interval_days*(orden-1)`, reutilizando `_compute_publish_at`.
- RF-7: El backend actualiza cada vídeo en secuencia; el fallo de uno no aborta el resto, y el resultado
  por vídeo (`done` / `error`) se consulta en `/api/status/<job_id>` como en el lote de Shorts.
- RF-8: Al actualizar un vídeo se reenvían los campos de `status` que ya tenía (`embeddable`, `license`,
  `publicStatsViewable`) junto con `privacyStatus: "private"` y `publishAt` (ver Riesgos, punto 1).
  `selfDeclaredMadeForKids` y `containsSyntheticMedia` no hace falta reenviarlos: la API los exime.
- RF-9: Con `DCS_SIMULATE=1` ambos endpoints devuelven datos de ejemplo y no llaman a YouTube.

### Requisitos no funcionales
- Cuota (verificada el 2026-10-18 en la documentación oficial, `determine_quota_cost` y `videos/update`):
  `channels.list`, `playlistItems.list` y `videos.list` cuestan 1 unidad; `videos.update` cuesta 50. Un lote
  de 15 vídeos son 750 unidades del bloque de 10.000 diarias por defecto para los endpoints que no son
  `search.list` ni `videos.insert`. Reinicio a medianoche, hora del Pacífico. No se usa `search.list`
  (100 llamadas al día): se lista por la playlist de subidas.
- Sin credenciales nuevas: `SCOPES` ya incluye `youtube` y `youtube.force-ssl`, y el token actual los cubre.
- Listar vídeos no gasta cuota de Gemini. Los tests mockean la API de YouTube; ninguno consume cuota real.

### Contratos afectados
- Nuevo `GET /api/youtube/pending_videos` devuelve `{"videos": [{video_id, title, uploaded_at, duration_sec, thumbnail_url, is_short}], "scheduled": [{video_id, title, publish_at, ...}]}`.
- Nuevo `POST /api/schedule_videos_batch` recibe `{"video_ids": [str], "first_publish_at": str (ISO 8601, Z), "interval_days": int}`
  y devuelve `{"job_id": str}`; el estado sale por `/api/status/<job_id>`.
- Cruza la frontera servidor ↔ navegador: exige verificación en navegador real con `run-app`.
- Sin cambios en `config.json` ni en `history.json`.

### Impacto en ficheros
- `youtube_uploader.py`: `list_pending_videos()` y `schedule_video(video_id, publish_at)`.
- `web/app.py`: dos endpoints y el hilo del lote, reutilizando `_compute_publish_at` y el patrón de `_run_shorts_batch`.
- `web/templates/index.html`: sección nueva (ver pregunta abierta 1).
- `tests/`: tests nuevos con la API mockeada. No toca `dcs_meta.py`.

### Dependencias externas
- YouTube Data API v3, ya instalada (`google-api-python-client`). Sin paquetes nuevos.

### Quality gates
`ruff check .` y `pytest` en verde en CI. Comprobación en navegador real de la lista, la tabla de
confirmación y el estado por vídeo.

### Riesgos y decisiones abiertas
**Riesgos**
1. Según la documentación de `videos.update`, si la petición no especifica una propiedad que ya tiene
   valor, ese valor se borra (salvo `selfDeclaredMadeForKids` y `containsSyntheticMedia`). Con `part=status`
   hay que leer el `status` actual con `videos.list` y reenviar `embeddable`, `license` y
   `publicStatsViewable`, más `privacyStatus: "private"` (obligatorio al fijar `publishAt`, aunque ya sea
   privado) y `publishAt`. Debe haber un test que lo cubra.
2. Un `publishAt` en el pasado hace que YouTube publique el vídeo al instante (la documentación lo equipara
   a pasar de `private` a `public`). La validación debe rechazar fechas anteriores a "ahora".
3. `publishAt` solo se puede fijar en vídeos privados **que nunca se han publicado**. Un vídeo que fue
   público y se volvió a poner privado aparecerá en la lista, pero la API lo rechazará: la API de
   listado no distingue ese caso, así que se trata como error por vídeo (RF-7), con el mensaje de YouTube.
4. Si la subida se hizo desde otro cliente, el listado puede incluir borradores a medio completar; el
   filtro `private` sin `publishAt` no los distingue.

**Decisiones de David (2026-10-18), todas según la propuesta**
1. UI: pestaña nueva "Pendientes" junto a Metadata, History, Stats y Setup.
2. Vídeos con `publishAt` futuro: se listan aparte, en solo lectura. No se reprograman en esta iteración.
3. Shorts ya subidos: se incluyen en la lista, con etiqueta "Short" (duración ≤ 3 min).
4. Orden: fecha de subida ascendente, sin reordenar a mano.
5. Tope: 15 por lote.

### Criterios de aceptación
- Con `DCS_SIMULATE=1`, la pestaña muestra una lista de ejemplo y permite programar el lote sin llamar a YouTube.
- Seleccionar 3 vídeos con primera fecha X e intervalo 3 muestra las fechas X, X+3d y X+6d en la tabla de
  confirmación y envía exactamente esas.
- Con 16 vídeos marcados, el decimosexto no se puede marcar y el endpoint devuelve 400 si se fuerza.
- Un `video_id` que falla (mock) queda en `error` y el resto del lote sigue.
- Un test comprueba que el `status` reenviado a `videos.update` conserva los campos que tenía el vídeo.
- Una fecha pasada se rechaza con 400.

---

## Feature: Edición automática del vídeo (cortes, highlights y corrección de imagen)

**Estado:** Aprobada 2026-10-18 (decisiones de David resueltas al final de "Riesgos y decisiones abiertas")
**Entrada de BACKLOG.md:** FEA-09

### Problema
Las grabaciones de DCS (de 30 min a varias horas, hasta ~9 GB) llevan tiempos muertos (rodaje, esperas,
cruceros largos), y hoy todo el montaje, los highlights y la corrección de imagen se hacen a mano en un
editor antes de subir el vídeo.

### Objetivo
Desde la app, proponer los cortes de tiempos muertos, montar un highlight a partir de los mejores momentos y
aplicar una corrección de imagen (color, contraste...), dejando siempre a David revisar antes de renderizar y
generando un fichero nuevo sin tocar el original. Los tiempos muertos se aceleran con música en vez de
cortarse (se puede elegir cortar), y la música cambia según la fase de vuelo.

### Por qué ffmpeg y no DaVinci Resolve (versión gratuita)
- El scripting de Resolve no es una vía: según un informe de terceros (Puget Systems, 2026-09-10) que cita
  las notas de la versión, Resolve 21.1 eliminó el scripting de la edición gratuita. No confirmado en las notas
  oficiales de Blackmagic; verificar si algún día se quisiera reabrir esta vía.
- Importar una línea de tiempo (EDL, XML u OTIO) por el menú es posible, pero no traslada las correcciones de
  color. Compatibilidad con la edición gratuita sin confirmar.
- ffmpeg 8.1 ya está instalado, con `h264_nvenc` y `hevc_nvenc` (RTX 4090) y los filtros necesarios (`eq`,
  `curves`, `colorbalance`, `lut3d`, `freezedetect`, `blackdetect`, `scdet`, `xfade`, `loudnorm`).

### Fuera de alcance
- Controlar Resolve u otro editor, o exportar EDL/FCPXML/OTIO (posible extra futuro).
- Editor de línea de tiempo completo: la revisión es una lista de tramos con casillas, no un NLE.
- Transiciones elaboradas, títulos o efectos. La música se limita a los tramos acelerados (RF-12 y RF-13) y
  al fondo del highlight (Fase 2); bajo el vídeo normal de la Fase 1 no hay música.
- Subida automática del resultado (sigue el flujo actual de Metadata y Pendientes).

### Entrega por fases (una PR por fase)
- **Fase 0, spike con medidas (hecha 2026-10-18, ver resultados al final):** probar las señales de tiempo muerto sobre 2 grabaciones reales (93 y 77 min,
  con ACMI), calcular el desfase entre el tiempo del ACMI y el del vídeo, y comprobar si la fase de vuelo
  (rodaje, despegue, navegación, aproximación y aterrizaje) se puede clasificar con la telemetría del ACMI.
  Decidir umbrales con datos. Sin UI.
- **Fase 1, cortes:** detectar tiempos muertos, lista de tramos editable en la UI, render del vídeo recortado.
  Se entrega en dos PRs: 1a (análisis y revisión en la pestaña Edición, hecha 2026-10-18) y 1b (audio, música y
  render, hecha 2026-10-18; la arquitectura del render y sus mediciones están en `DECISIONS.md`).
- **Fase 2, highlights:** montar un vídeo horizontal 16:9 con los mejores momentos.
- **Fase 3, imagen:** vista previa antes/después y aplicación de la corrección en el mismo render.

### Requisitos funcionales
- RF-1 (Fase 1): `POST /api/edit/analyze_cuts` devuelve, por job, los tramos propuestos como
  `[{start, end, reason}]` más la duración original y la resultante.
- RF-2 (Fase 1): La UI muestra los tramos con una acción por tramo (acelerar, cortar o conservar; acelerar
  por defecto), se pueden ajustar inicio y fin, y se ve la duración resultante antes de renderizar. Nada se
  renderiza sin pulsar el botón.
- RF-3 (Fase 1): `POST /api/edit/render` recibe los tramos a conservar y genera `output/edits/<nombre>_editado.mp4`.
  Nunca sobrescribe el original ni un fichero existente (se añade sufijo numérico).
- RF-4 (Fase 1): El render informa de progreso por `/api/status/<job_id>` y mantiene el audio sincronizado.
- RF-5 (Fase 2): Seleccionar N momentos (los de `_collect_candidate_timestamps` y su puntuación, reutilizados)
  y montar un highlight 16:9 con una duración objetivo, por defecto 9 minutos (rango 8 a 10, configurable).
  Los tramos se unen con fundido corto (ver RF-9).
- RF-9: Entre tramos conservados se aplica un fundido de 0,3 s por defecto (`xfade` y `acrossfade`), con
  opción de corte seco. Cada fundido solapa 0,3 s, así que la duración resultante lo descuenta.
- RF-6 (Fase 3): La corrección de imagen es automática, sin deslizadores ni LUT. La app mide el vídeo
  (muestreo de frames, estadísticas de luminancia y color) y calcula sola los ajustes de contraste,
  niveles, saturación y balance con filtros de ffmpeg (`eq`, `colorlevels`, `colorbalance`, `curves`),
  acotados a una intensidad moderada para no estropear tomas que ya están bien.
- RF-7 (Fase 3): `GET /api/edit/preview_frame` devuelve el original y el corregido de un mismo frame para
  compararlos, y el render aplica la corrección en la misma codificación que los cortes. Una casilla
  permite desactivarla.
- RF-8: Con `DCS_SIMULATE=1` los endpoints responden con datos de ejemplo y no ejecutan ffmpeg.
- RF-10 (Fase 1): Un tramo acelerado reduce su duración con `setpts` y descarte de fotogramas. La velocidad es
  automática según la duración del tramo: objetivo de unos 20 s por tramo, entre 4x y 16x; si aun así
  excede, el sobrante se corta. Se puede editar a mano en la revisión.
- RF-11 (Fase 1): La fase de vuelo de cada tramo (rodaje y despegue, navegación, aproximación y aterrizaje)
  se clasifica con la telemetría del ACMI, corrigiendo el desfase entre el tiempo del ACMI y el del vídeo
  (medido en la Fase 0). Se muestra en la lista y se puede corregir a mano.
- RF-12 (Fase 1): Audio: en los tramos a velocidad normal, las 3 pistas de la grabación (general, radio y
  micro) se fusionan en una sola pista; en los tramos acelerados el audio original se sustituye por música.
- RF-13 (Fase 1): Música: una carpeta configurable con 3 subcarpetas, una por fase (rodaje y despegue,
  navegación o tiempo muerto, aproximación y aterrizaje). Se elige una pista al azar de la subcarpeta de la
  fase del tramo, sin repetir en el mismo vídeo mientras haya otras, con fundido de 1 s. La app no descarga
  ni genera música. Sin pistas en la subcarpeta, el tramo se acelera en silencio y se avisa.

### Requisitos no funcionales
- Local, sin llamadas a Gemini ni a YouTube: no consume cuota.
- Codificación por defecto con `h264_nvenc` (compatible con YouTube), calidad configurable; el audio se
  recodifica a AAC, con `loudnorm` opcional.
- Grabaciones de hasta ~9 GB: todo en hilo de fondo con progreso y con espacio en disco comprobado antes de
  empezar (aborta con mensaje claro si no hay sitio).
- Validación de rutas: `video_path` debe existir y ser un vídeo; las salidas solo se escriben bajo
  `output/edits/` (relación con SEC-02/FEA-05).

### Contratos afectados
- Nuevos `POST /api/edit/analyze_cuts`, `POST /api/edit/render`, `POST /api/edit/highlights` y
  `GET /api/edit/preview_frame`; los jobs usan `processing_status` como el resto.
- Nuevas claves en `config/config.json` para la calidad de codificación, la duración objetivo del highlight,
  la duración del fundido, la carpeta de música y los nombres de las 3 subcarpetas por fase. Sin claves de presets de color: la corrección es automática.
- Cruza la frontera servidor ↔ navegador: exige verificación en navegador real con `run-app`.

### Impacto en ficheros
- Nuevo módulo plano `video_edit.py` (mismo patrón que `acmi.py` y `thumbnail.py`; no se engorda `dcs_meta.py`,
  coherente con TEC-01). Reutiliza `_get_video_duration`, el parseo de `silencedetect`, `parse_acmi_events` y
  la puntuación de candidatos de `dcs_meta.py`, con el acoplamiento que hay hasta TEC-01c.
- `web/app.py`: endpoints y jobs. `web/templates/index.html`: pestaña nueva "Edición".
- `tests/`: construcción de comandos ffmpeg con subproceso mockeado, y pruebas con ffmpeg real sobre clips
  sintéticos de pocos segundos (se omiten si no hay ffmpeg).

### Dependencias externas
- Ninguna nueva: ffmpeg ya es requisito (Pillow, ya instalado, sirve para medir los frames).
- Música: la aporta David en la carpeta configurada. La licencia es suya: YouTube puede reclamar con Content ID
  cualquier pista con copyright; lo seguro es la biblioteca de audio de YouTube o pistas con licencia propia.

### Quality gates
`ruff check .` y `pytest` en verde en CI. Comprobación en navegador real de la lista de tramos, la vista previa
y el render sobre un clip corto.

### Riesgos y decisiones abiertas
**Riesgos**
1. El audio de DCS rara vez calla (motor, radio). En la medición de TEC-06, un vídeo de 46 min devolvió 1
   silencio con `silencedetect`, así que el silencio por sí solo no sirve. De ahí la Fase 0: medir otras
   señales (nivel de audio relativo, movimiento de imagen con `scdet`, fotogramas congelados o negros, tramos
   sin eventos ACMI) antes de fijar umbrales.
2. Un umbral agresivo puede cortar momentos buenos. Se mitiga con revisión obligatoria antes de renderizar.
3. Cortar sin recodificar solo es exacto en fotogramas clave; por eso se recodifica con NVENC.
4. David confirma que sus grabaciones llevan siempre ACMI, así que es la señal principal. Si falta, la
   app avisa de que la detección será menos fiable y usa solo audio e imagen.
5. Tiempo y espacio en disco con grabaciones de 2 a 3 horas.
6. Los fundidos con muchos tramos generan filtros muy grandes (`xfade` encadenado). El plan de la Fase 1 debe
   decidir si se renderiza por bloques y se une después, y medirlo con un caso de 50 o más tramos.
7. La corrección automática puede empeorar tomas ya buenas: intensidad acotada, casilla para desactivarla y
   vista previa antes/después. Hay que ajustarla con grabaciones reales.
8. Clasificar la fase de vuelo con telemetría del ACMI puede fallar (p. ej. en portaaviones, donde el rodaje
   y el aterrizaje no se parecen a los de una pista). La Fase 0 lo mide con las 2 grabaciones y, si no es
   fiable, la fase se asigna a mano en la revisión.
9. El tiempo del ACMI y el del vídeo no coinciden (p. ej. 20 min de diferencia en la grabación del 17 de
   octubre): sin corregir el desfase, los tramos y las fases quedarían desplazados.
10. Fusionar 3 pistas puede dejar la radio o el micro tapados por el juego: normalizar con `loudnorm` y
    comprobar el balance en la Fase 1.

**Decisiones de David (2026-10-18)**
1. Entrega por fases 0, 1, 2 y 3, en PRs separadas.
2. Revisión siempre obligatoria antes de renderizar, sin modo automático.
3. Salida h264 NVENC en MP4 en `output/edits/`, sin tocar el original.
4. Corrección de imagen totalmente automática, sin LUT ni deslizadores.
5. Fundido entre tramos (0,3 s por defecto, con opción de corte seco).
6. Las grabaciones llevan siempre su ACMI asociado.
7. Duración del highlight a criterio de Claude para YouTube: 9 minutos por defecto (rango 8 a 10), porque la
   [documentación de YouTube](https://support.google.com/youtube/answer/6175006?hl=en) indica que los anuncios
   intermedios solo están disponibles en vídeos monetizados de 8 minutos o más. Aplica solo si el canal
   está monetizado (no verificado); si no, convendría un highlight más corto. La retención de audiencia
   no se ha medido.
8. Tiempos muertos acelerados con música, en vez de cortados (se puede cortar por tramo).
9. Audio del juego sustituido por la música en los tramos acelerados.
10. En los tramos normales, las 3 pistas (general, radio y micro) se fusionan en una.
11. Música por fase de vuelo: rodaje y despegue, navegación o tiempo muerto, y aproximación y aterrizaje.
12. En la fusión de audio se descartan automáticamente las pistas vacías (p. ej. el micro en misiones monojugador) o
    duplicadas.

### Criterios de aceptación
- Fase 0: un informe con, para 2 o 3 grabaciones reales, qué señales detectan tiempos muertos y con qué
  falsos positivos, y los umbrales propuestos.
- Fase 1: sobre un clip sintético con un tramo plano conocido, la lista propone ese tramo, el render lo
  elimina y la duración resultante coincide con la mostrada (±1 fotograma), con audio sincronizado.
- El original nunca se modifica y un nombre de salida existente no se sobrescribe.
- Fase 0: el desfase ACMI-vídeo calculado coincide, en las 2 grabaciones, con la comparación manual de al menos
  un evento (p. ej. despegue) en ambos tiempos, y la clasificación de fases acierta en los tramos revisados.
- Fase 1: un tramo muerto largo sale acelerado con la música de su fase y el audio original silenciado, y
  vuelve el audio normal fusionado al acabar el tramo, sin saltos de sincronía.
- Fase 2: el highlight dura lo pedido (±5 %) y contiene los momentos de mayor puntuación.
- Fase 3: la vista previa y el render dan el mismo aspecto sobre el mismo frame.

### Detalle de la Fase 2: highlights (borrador 2026-10-20, pendiente de aprobación)

Decisiones de David (2026-10-20): ventana de recorte por tipo de evento, relleno con tramos de navegación si no
se llega al mínimo, orden cronológico y música de fondo bajo el audio original.

**Flujo.** Pestaña Edición, modo "Highlight": `POST /api/edit/highlights` (job) devuelve los tramos propuestos;
David los revisa (casilla por tramo, inicio y fin editables, duración resultante) y pulsa render. Nada se
renderiza sin pulsar el botón. El render reutiliza el de la Fase 1: el highlight se expresa como una lista de
tramos a conservar y el resto se corta, así que no hay un segundo camino de render.

**Selección (RF-5 concretado).**
1. Cada evento ACMI (ya en tiempo de vídeo) abre una ventana según su tipo. Propuesta de partida, ajustable con
   grabaciones reales: kill 20 s antes y 10 s después; eyección 15 y 10; bomba guiada 20 y 15; SAM 15 y 10; BVR 20 y 15.
2. Las ventanas que se solapan o distan menos de 5 s se funden en un solo tramo.
3. Se añaden por prioridad de tipo (kill, eyección, bomba guiada, SAM, BVR, el orden de `_deduplicate_candidates`)
   hasta alcanzar la duración objetivo (9 min por defecto, tope 10). Si un tramo hace pasar de 10 min, se salta.
4. Si el total queda por debajo de 8 min, se rellena con tramos de navegación, marcados "relleno" en la lista:
   primero el despegue (máx. 45 s) y la aproximación con aterrizaje (máx. 90 s, con el aterrizaje completo y sin
   acelerar), y luego ventanas de 30 s repartidas por la navegación no estática, hasta llegar a 8 min.
5. Orden cronológico. Entre tramos, fundido de 0,3 s (RF-9).

**Audio.** Tramos con el audio original fusionado como en la Fase 1 y, debajo, una pista de música de fondo
continua con fundido de 1 s al inicio y al final. Pista al azar de la subcarpeta `highlight` de `music_folder`
(nueva, además de las 3 por fase), en bucle si es más corta que el vídeo. Volumen fijo relativo, clave
`highlight_music_db` (por defecto -20). Sin ducking en esta fase. `# ponytail:` si hiciera falta bajar la música
con la radio, se amplía con `sidechaincompress`. Subcarpeta vacía: sin música y aviso, no se bloquea el render.

**Contratos.** `POST /api/edit/highlights` con `{video_path, acmi_path, acmi_offset_s?, target_s?}`; resultado
`{segments: [{start, end, reason, event_type?}], duration_s, offset_s, warnings}`. `POST /api/edit/render` admite
música de fondo opcional. Nuevas claves: `highlight_target_s` (540) y `highlight_music_db` (-20).

**Pruebas.** Selección con eventos sintéticos (ventanas, fusión, prioridad, tope de 10 min, relleno), y render
con ffmpeg real sobre un clip corto con música de fondo.

**Criterios de aceptación.** El highlight dura lo pedido (±5 %), contiene las ventanas de mayor prioridad, queda en
orden cronológico, el aterrizaje de relleno no se acelera y la música de fondo no tapa el audio original.

### Resultados de la Fase 0 (2026-10-18)

**Muestra.** `op_green_line-05.mkv` (77 min) y `2026-10-17_00-34-43.mkv` (93 min), ambas 1080p60 H.264 con 3
pistas de audio, y su ACMI. Aeronave FA-18C, despegue desde portaaviones en las dos. Medida solo de lectura.

**1. Desfase ACMI-vídeo (resuelto).**
- `RecordingTime` de la cabecera del ACMI está en UTC; el nombre de fichero de Tacview y el de OBS están en hora
  local (UTC+2 en las dos grabaciones). Tiempo de vídeo = tiempo ACMI menos el desfase.
- 17 de octubre: el vídeo empieza 1215 s después del ACMI (vídeo 00:34:43 local frente a ACMI 00:14:28 local).
  Comprobado con imagen: el despegue previsto a los 12 s del vídeo coincide con el fotograma (cubierta a los 0 s,
  en el aire a los 12 s). Margen de error observado de unos 5 s. Además 1215 + 5605 s da 6820 s frente a 6778 s
  de duración del ACMI.
- `op_green_line-05`: desfase aproximado 0 s, comprobado con imagen (despegue previsto a los 584 s). El nombre de
  este fichero no lleva marca de tiempo, así que ahí el desfase hay que obtenerlo de otra fuente (ver propuestas).
- El código actual (`detect_short_clips()`) usa los tiempos del ACMI como tiempos del vídeo, sin desfase. Anotado
  como BUG-06 en `BACKLOG.md`.

**2. Telemetría disponible.** El objeto del jugador (`Pilot` igual a su nombre) trae `AGL`, `IAS`,
`LandingGear`, `Throttle`, `Flaps`, `AirBrakes`, `AOA`, rumbo (`HDM`) y posición de los mandos, con un dato por
segundo en las dos grabaciones. El parser actual (`parse_acmi_events`) solo extrae eventos de combate, no esta
telemetría.

**3. Qué señales sirven.**

| Señal | Resultado |
|---|---|
| Telemetría ACMI | Fiable. Separa rodaje, despegue, navegación estática y aproximación. |
| Movimiento de imagen (`YDIF` a 1 fps) | No sirve. Mediana ~24 en tramos muertos y en activos (grabación en VR, la cabeza se mueve siempre). Un detector solo de imagen marcó 0 min. |
| Fotogramas congelados o negros | Marginal: 1 y 33 s congelados, 0 negros. |
| Nivel de audio (3 pistas) | Débil. Pistas muy bajas (-51 y -65 dBFS de mediana). Solo en la del 17 de octubre se nota diferencia (-79 dB en muertos, -65 dB en activos). |
| Micrófono (pista 3) | Vacío en `op_green_line-05` (-120 dB) y activo ~6% del tiempo en la otra. |

Las pistas 1 y 2 de `op_green_line-05` dieron estadísticas idénticas (duplicadas o misma mezcla); no verificado.

**4. Reglas propuestas (umbrales medidos).**
- **Fase por segundo:** `rodaje` si tren abajo, `IAS` menor de 60 kt y `AGL` menor de 30 m (en portaaviones la
  cubierta marca 22 m); `despegue` si tren abajo, volando por debajo de 600 m tras un rodaje reciente;
  `aproximacion` si tren abajo y en el aire sin rodaje reciente; `navegacion` con tren arriba. Se absorben
  segmentos de menos de 15 s. En los datos, rodaje y despegue se funden bien, como pide la carpeta de música.
- **Navegación estática:** ventana de 60 s con rango de altitud menor de 100 m, de `IAS` menor de 15 kt, de rumbo
  menor de 10 grados y movimiento de mandos casi nulo.
- **Tramo muerto:** rodaje o navegación estática durante al menos 60 s, sin eventos de combate a menos de 20 s,
  recortando 10 s por extremo y descartando lo que quede por debajo de 40 s.

**5. Resultado sobre las dos grabaciones.**

| Grabación | Tramos muertos (con márgenes) | Vídeo final acelerando 4x a 16x |
|---|---|---|
| `op_green_line-05` (77 min) | 27 min (35%): 10 min de cubierta al inicio y 5 tramos de crucero | ~53 min |
| `2026-10-17_00-34-43` (93 min) | 4 min (4%): crucero y rodaje en pista | ~90 min |

Con hojas de contactos de 27 fotogramas, los tramos propuestos son tiempo realmente muerto (rodaje, esperas, crucero
sobre las nubes). Corrección (Fase 1a): este informe decía que el último tramo de `op_green_line-05` (4529 a 4620 s)
incluía los últimos segundos de la aproximación. La telemetría muestra que el toque ocurre en 4518 a 4521 s (la `IAS`
baja de 160 a 52 kt), así que ese tramo es la cubierta tras el aterrizaje y termina con el cartel "MISSION SUCCESS".
No había falso positivo claro en los fotogramas revisados. No se ha contrastado con rangos de tiempo muerto elegidos por David.

**6. Rendimiento medido (RTX 4090, NVDEC y NVENC `h264_nvenc`).**
- Imagen a 1 fps de 93 min: 331 s. Audio de una pista: 6 s. Como la imagen no sirve, no se usará.
- Render normal: unas 5,7 veces tiempo real (un vídeo de 90 min saldría en ~16 min).
- Acelerar x12: 600 s de origen en 36 s. `xfade` de 0,3 s entre tramos: sin penalización medible en dos tramos.
- Con `-cq 19` el fichero sale a ~27 Mbps frente a los ~10 Mbps del original: usar un `-cq` más alto (a decidir
  en la Fase 1 comparando calidad).

**7. Consecuencias para la especificación.**
- La detección de tiempos muertos se basa en la telemetría del ACMI; no usa la imagen ni el audio.
- Hace falta un parser de telemetría nuevo (hoy solo hay eventos) y un cálculo de desfase con `RecordingTime`.
- Fuentes del inicio del vídeo, por orden: marca de tiempo del nombre de fichero (OBS), metadatos del contenedor y,
  en último caso, un ajuste manual en la UI con el despegue como referencia.
- La Fase 1 puede arrancar. Pendiente de David: elegir las pistas de audio que se conservan (pista 3 vacía en una
  grabación) y comprobar tramos concretos.

**Límites.** Solo 2 grabaciones, ambas FA-18C con salida de portaaviones. Las reglas de fase no se han probado con
otras aeronaves ni con aterrizajes en pista.

---

## Contexto permanente del producto

Esto no se renegocia por feature; es el marco en el que encaja todo lo demás. Verificado contra el código
actual.

- **Usuario único:** David. Aplicación local, sin multiusuario ni despliegue en nube.
- **Objetivo del producto:** reducir a minutos el trabajo manual de preparar y publicar un vídeo de DCS
  World en el canal @TheCylonPilot.
- **Ningún vídeo se publica sin revisión humana.** La subida es siempre `private`; la publicación es una
  decisión aparte.
- **Idiomas de salida:** inglés por defecto; español para misiones del Escuadrón 111.
- **Coste:** Gemini y la YouTube Data API tienen cuota. Cualquier feature que multiplique las llamadas
  necesita justificación explícita del coste.
- **Sin build step en frontend.** La UI es un único HTML con su JS embebido, servido por Flask.

---

## Preguntas abiertas para David

Pendientes de respuesta. El Tech Lead las traslada; ningún otro agente pregunta directamente.

1. **Prioridad de SEC-01.** `config/config.json` está rastreado en git y la pestaña Setup escribe ahí
   `discord_bot_token`. Hoy está vacío, pero en cuanto lo rellenes y hagas commit, el token queda público.
   ¿Se arregla antes que cualquier otra cosa?
2. **Alcance del CI.** No existe `.github/workflows/`. La Definition of Done exige CI real en verde, así
   que hoy es incumplible. ¿Qué debe correr el CI en la primera versión: solo pytest, o también linter y
   umbral de cobertura?
   **Respuesta (2026-07-26):** pytest + linter (`ruff`) + coverage (`pytest-cov`), los tres bloqueantes
   desde el primer CI. Coverage se mide y reporta pero sin umbral mínimo (ver pregunta 3). Pendiente de
   ejecutar: INF-01 (crear `.github/workflows/`).
3. **Umbral de cobertura.** ¿Qué porcentaje mínimo aceptas como quality gate, sabiendo que `dcs_meta.py`
   concentra la mayor parte de la lógica?
   **Respuesta (2026-07-26):** sin umbral bloqueante por ahora. Se mide y reporta (`--cov-report=term-missing`
   en `pytest.ini`), no falla el build por debajo de un %.
4. **Refactor de `dcs_meta.py`.** Son ~2.200 líneas mezclando dominio, I/O, subprocesos y HTTP. Partirlo
   mejora el cumplimiento de la regla 4 (SOLID) pero es una PR grande y arriesgada. ¿Se aborda ahora, se
   hace de forma incremental, o se congela?
   **Respuesta (2026-07-26):** incremental, una PR por dominio (TEC-01a–e en `BACKLOG.md`), en orden de
   menor a mayor acoplamiento: `acmi/` → `thumbnail/` → `media/` → `gemini/` → `seo/`. `dcs_meta.py`
   reexporta cada símbolo movido, así ninguna PR toca los 47 call sites en `web/app.py`,
   `discord_bot.py`, `batch_watcher.py` y `youtube_uploader.py`.
5. **Tests que consumen cuota real.** ¿Autorizas una suite marcada de tests de integración contra Gemini
   y YouTube que se ejecute solo bajo petición, o todo debe ir mockeado siempre?
6. **Versionado.** ¿Empezamos a etiquetar releases con tags de git a partir de la próxima entrega, o el
   `CHANGELOG.md` basta?
   **Respuesta (2026-07-26):** tags de git, a partir de la próxima entrega. Ver `DECISIONS.md`. La
   primera etiqueta espera a que INF-01 (CI) y SEC-01 estén resueltos (ver `CHANGELOG.md`).
7. **`README.md` desactualizado.** No documenta Shorts, ACMI, debrief, narración, captions, Stats, watcher
   de lotes ni el bot de Discord. ¿Lo actualizamos como tarea propia o se va arreglando por partes?
