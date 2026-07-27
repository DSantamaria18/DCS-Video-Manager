# ARCHITECTURE.md — DCS Video Manager

Arquitectura de la aplicación. Documento vivo: actualízalo en la misma PR que cambie la estructura,
las fronteras entre módulos o las integraciones externas.

> Este documento se ha reconstruido leyendo el código de `main`. Todo lo que afirma está verificado
> contra el fuente. Donde hay incertidumbre, se dice explícitamente.

---

## 1. Visión general

Aplicación **local, monousuario, sin dependencias de nube propias**. Se ejecuta en el PC de David y
automatiza el ciclo completo de publicación de un vídeo de DCS World en YouTube:

```
vídeo .mkv/.mp4  ──►  extracción de frames (ffmpeg)  ──►  análisis Gemini Vision  ──►  metadatos
                                                                                          │
                              (opcional) TacView .acmi ────────────────────────────────────┤
                              (opcional) tags/capítulos OBS del MKV ──────────────────────┤
                              (opcional) marcadores de audio (silencedetect) ─────────────┘
                                                                                          │
        edición manual en la UI  ◄───────────────────────────────────────────────────────┘
                    │
                    ├──►  miniatura (Pillow)          ──►  thumbnails.set
                    ├──►  clips Shorts 9:16 (ffmpeg)  ──►  descarga manual
                    └──►  subida YouTube Data API v3  ──►  history.json + polling de analytics
                                                              │
                                                              └──►  webhook / bot de Discord
```

No hay base de datos. **Todo el estado persistente son ficheros JSON en disco.**

---

## 2. Componentes

| Módulo | Responsabilidad | Notas |
|---|---|---|
| `dcs_meta.py` | Motor de dominio: config, memoria, extracción de frames, construcción del prompt, llamada a Gemini, debrief, SEO, Shorts, salida a disco. También expone una CLI (`main()`). | ~1.840 líneas. Monolito en extracción incremental por dominios (TEC-01, ver §7). |
| `acmi.py` | Parsing de ficheros TacView `.acmi`: kills, lanzamientos SAM/BVR/IR, bombas guiadas, pérdidas propias, eyecciones. | Extraído de `dcs_meta.py` (TEC-01a). Reexportado desde `dcs_meta` para no romper call sites existentes. |
| `thumbnail.py` | Selección y puntuación de frames candidatos, gradación cinematográfica, overlay estilo YouTube, guardado JPEG bajo 2 MB. | Extraído de `dcs_meta.py` (TEC-01b). Reexporta solo `generate_thumbnail_on_demand` (única función usada fuera del módulo); los helpers `_load_font`/`_score_frame`/etc. son internos. |
| `web/app.py` | Capa HTTP: servidor Flask, endpoints REST, orquestación de trabajos en background, selector de ficheros nativo del SO. | Importa `dcs_meta` inyectando el directorio padre en `sys.path`. |
| `web/templates/index.html` | Toda la UI: HTML, CSS y JavaScript en un único fichero. Pestañas Metadata / History / Stats / Setup. | Sin framework ni build step. |
| `youtube_uploader.py` | Integración con Google: OAuth2, subida resumible, playlists, miniatura, YouTube Analytics API v2. | Importa `dcs_meta` *dentro* de una función para el polling de analytics. |
| `batch_watcher.py` | Vigila la carpeta de grabaciones y encola los `.mkv` nuevos. | Usa `watchdog`, importado de forma perezosa. |
| `discord_bot.py` | Bot standalone de Discord para el Escuadrón 111 (`!debrief`, `!stats`, registro de reacciones). | Proceso independiente. No lo arranca la app web. |
| `tests/` | Suite pytest. | |

### Dependencia entre módulos

```
web/app.py ──► dcs_meta.py ◄── youtube_uploader.py
     │              ▲
     ├──► youtube_uploader.py
     └──► batch_watcher.py

discord_bot.py  (independiente, solo lee memory/history.json, config/config.json y config/secrets.json)
```

`youtube_uploader.schedule_analytics_polling()` accede a `dcs_meta._memory_lock`, un símbolo privado
de otro módulo. Es un acoplamiento conocido y anotado como deuda técnica.

---

## 3. Flujos principales

### 3.1 Análisis de un vídeo

1. `GET /api/browse` abre el diálogo nativo del SO (PowerShell en Windows, `osascript` en macOS,
   `zenity` en Linux) y recuerda la última carpeta en `config/last_folder.txt`.
2. `POST /api/analyze` valida que el fichero existe y que `GEMINI_API_KEY` está en el entorno,
   crea un `job_id` de 8 caracteres y lanza un hilo daemon. Responde inmediatamente con el `job_id`.
3. El hilo ejecuta: `extract_frames()` → `generate_metadata()` → `save_output()` → `update_memory()`,
   actualizando `processing_status[job_id]` con `progress` y `message` en cada etapa.
4. El navegador hace polling contra `GET /api/status/<job_id>`.
5. Si `generate_metadata()` lanza, se captura y se usa `build_fallback_metadata()`: se deriva un título
   del nombre de fichero y del contexto, y la UI muestra un aviso ámbar. **La subida sigue siendo posible.**

### 3.2 Construcción del prompt de Gemini

`build_prompt()` compone un único prompt de texto con bloques opcionales. Las fuentes de contexto son:

- Contexto libre escrito por David.
- `MODULE_PROFILES`: identificadores de cabina, misiones típicas, armamento y variantes de tags por módulo.
- Historial: últimos vídeos de `memory/history.json`, para mantener consistencia de estilo.
- `SERIES CONTEXT`: campaña y número de episodio detectados por `_detect_series()` sobre el contexto,
  con enlaces `https://youtu.be/<id>` a episodios previos si ya tienen `video_id`.
- `AUDIO PHASE MARKERS`: timestamps de `ffmpeg silencedetect` (−30 dB, 3 s), filtrados a un mínimo de
  60 s entre marcadores, máximo 8, descartando los del último 10% del vídeo.
- `TACVIEW ACMI DATA`: eventos tácticos de `parse_acmi_events()`.
- `OBS SCENE CONTEXT`: tag `DESCRIPTION` y capítulos del MKV vía ffprobe.
- Plantilla de descripción según idioma (`en`/`es`) y duración (`short` <10 min, `medium` 10–30 min,
  `long` >30 min).

El idioma se decide con `is_squadron_video()`, que busca `SQUADRON_KEYWORDS` en el contexto.

### 3.3 Llamada a Gemini

`call_gemini()` usa **`urllib.request` directamente contra la API REST**, no el SDK de Google. Los frames
viajan en base64. `_recover_json()` intenta rescatar la respuesta cuando Gemini devuelve JSON malformado
o envuelto en markdown.

Modelos permitidos (allowlist en `web/app.py::VALID_MODELS`): `gemini-2.5-flash`, `gemini-2.5-pro`,
`gemini-1.5-flash`, `gemini-1.5-pro`.

### 3.4 Subida a YouTube

1. OAuth2 con `InstalledAppFlow` (tipo *Desktop app*): `get_auth_url()` arranca un hilo que abre el
   navegador y levanta un servidor local en puerto efímero; `wait_for_auth()` bloquea hasta 3 minutos.
   El token se guarda en `config/youtube_token.json` y se refresca automáticamente si expira.
2. `POST /api/upload_youtube` lanza un hilo y devuelve `job_id`; el progreso llega por
   `progress_callback` conectado al `resumable_progress` del `MediaFileUpload` (chunks de 10 MB).
3. `_sanitize_tags()` normaliza Unicode a ASCII, deduplica sin distinguir mayúsculas, recorta cada tag a
   30 caracteres y trunca el conjunto al límite de 500 caracteres de YouTube.
4. Si Google rechaza los tags con `invalidTags` (límite de apps no verificadas), se reintenta la subida
   sin tags y se marca `tags_skipped`.
5. Tras la subida: asignación a playlists, `thumbnails.set` (fallo no fatal),
   `update_memory_video_id()`, y `schedule_analytics_polling()`.

**Privacidad:** siempre se sube como `private`. Si se pasa `publish_at`, se fija `status.publishAt` para
publicación programada.

### 3.5 Polling de analytics

`schedule_analytics_polling()` programa cuatro `threading.Timer` daemon a 1 h, 6 h, 12 h y 24 h. Cada uno
consulta la YouTube Analytics API v2 y anexa el resultado a `entry["analytics"]` en `history.json`,
protegido por `dcs_meta._memory_lock`.

**Límite conocido:** los timers son daemon y viven en el proceso Flask. Si la app se cierra antes de las
24 h, los polls pendientes se pierden. No hay persistencia ni reintento.

---

## 4. Estado y persistencia

| Fichero | Contenido | En git |
|---|---|---|
| `config/config.json` | Nombre de canal, descripción, escuadrón, enlaces, nº de frames, modelo Gemini, `recordings_folder`. | **Sí (rastreado)** |
| `config/secrets.json` | `discord_webhook_url`, `discord_bot_token`, `discord_channel_id` (SEC-01: separados de `config.json` porque son editables desde la UI y no deben acabar en un commit). | No (`.gitignore`) |
| `config/client_secret.json` | Credenciales OAuth2 de Google. | No (`.gitignore`) |
| `config/youtube_token.json` | Token OAuth2 persistido. | No (`.gitignore`) |
| `config/last_folder.txt` | Última carpeta usada en el selector de ficheros. | No (`.gitignore`) |
| `memory/history.json` | Vídeos analizados: fecha, fichero, aeronave, mapa, tipo de misión, título, campaña, `video_id`, `analytics[]`, `debrief`. | No (`.gitignore`) |
| `memory/discord_reactions.json` | Reacciones registradas por el bot. | No |
| `output/` | Metadatos `.txt` y `.json`, miniaturas `.jpg`, `output/shorts/` con clips 9:16. | No (`.gitignore`) |

**Estado en memoria:** `web/app.py::processing_status`, un diccionario global `job_id → {status,
progress, message, result, error}`, acotado a 50 entradas por `_evict_old_jobs()`. Se pierde al reiniciar.

`GEMINI_API_KEY` se lee **exclusivamente del entorno**, nunca de `config.json` ni de `secrets.json`.
No tiene campo en la UI, a diferencia de los secretos de Discord (ver arriba).

---

## 5. Superficie HTTP

Todos los endpoints viven en `web/app.py`. El servidor escucha en `localhost:5000` con `debug=False`.

**Ficheros y análisis**

- `GET /` — UI.
- `GET /api/browse`, `GET /api/browse_acmi` — selectores nativos del SO.
- `POST /api/analyze` — arranca el job de análisis. Devuelve `job_id`.
- `GET /api/status/<job_id>` — estado del job.
- `POST /api/parse_acmi` — eventos tácticos de un `.acmi`.
- `POST /api/obs_metadata` — tags y capítulos del MKV.
- `GET /output/<filename>`, `GET /output/shorts/<filename>` — servir artefactos generados.

**Metadatos y calidad**

- `POST /api/thumbnail` — genera 4 candidatas de miniatura.
- `POST /api/seo_check`, `POST /api/seo_rewrite` — validación SEO y reescritura asistida.
- `POST /api/upload_checklist` — checklist previo a la subida.
- `POST /api/check_duplicate` — comparación contra el historial.
- `POST /api/debrief`, `POST /api/narration`, `POST /api/social_captions` — generaciones adicionales con Gemini.
- `POST /api/generate_shorts` — job de detección y recorte de clips 9:16.

**YouTube**

- `GET /api/youtube/auth_url`, `GET /api/youtube/wait_auth`, `GET /api/youtube/status`,
  `POST /api/youtube/revoke`.
- `GET /api/playlists`, `POST /api/suggest_playlists`.
- `POST /api/upload_youtube`.
- `GET /api/analytics/<video_id>`.
- `GET /api/competitors?aircraft=&mission_type=`.

**Configuración e historial**

- `GET /api/config`, `POST /api/config` — `POST` valida `frames_to_extract` (1–20) y `model` (allowlist),
  y aplica semántica de *merge* a `description_templates` para no pisar plantillas no editadas.
- `GET /api/description_templates`.
- `GET /api/history`, `GET /api/stats`, `GET /api/export_history_csv`.
- `POST /api/batch/start`, `POST /api/batch/stop`, `GET /api/batch/status`.

### Frontera servidor ↔ navegador

`web/templates/index.html` consume estos endpoints con `fetch` desde JavaScript. **Los tests de pytest
sobre el cliente de test de Flask no ejecutan ese JavaScript.** Cualquier cambio en la forma de un
payload o en el contrato de un endpoint necesita verificación en navegador real, no basta con tests
verdes (ver `CLAUDE.md`, sección de verificación).

---

## 6. Modelo de concurrencia

- Cada trabajo largo (análisis, subida, Shorts) corre en un `threading.Thread(daemon=True)`.
- La comunicación con el navegador es **polling**, no websockets ni SSE.
- `dcs_meta._memory_lock` protege lectura-modificación-escritura de `history.json`.
- `processing_status` **no** está protegido por lock. Las escrituras son asignaciones a claves distintas
  por job, lo que en CPython resulta seguro en la práctica, pero no es una garantía explícita del diseño.
- El watcher de carpeta corre en su propio hilo con un `Observer` de `watchdog`.

---

## 7. Límites conocidos y deuda estructural

Verificado en el código; cada punto tiene su entrada correspondiente en `BACKLOG.md`.

1. **`dcs_meta.py` es un monolito de ~1.840 líneas** que mezcla configuración, I/O de ficheros,
   invocación de subprocesos ffmpeg, cliente HTTP de Gemini y reglas de negocio de SEO. Viola la
   regla 4 (SOLID) y dificulta el testing por comportamiento. Extracción por dominios en curso
   (TEC-01a–e en `BACKLOG.md`); ACMI (`acmi.py`, TEC-01a) y miniaturas (`thumbnail.py`, TEC-01b) ya
   están fuera.
2. **Sin protección CSRF ni autenticación** en los endpoints `POST`. El servidor es local, pero cualquier
   página abierta en el navegador puede hacer peticiones a `localhost:5000`, y varios endpoints leen y
   escriben ficheros arbitrarios del disco a partir de rutas del payload.
3. **`_open_file_dialog()` interpola cadenas dentro de un script PowerShell y de un AppleScript.** Los
   valores vienen de `config/last_folder.txt`, no de red, pero el patrón es frágil.
4. **`watchdog` no está en `requirements.txt`** pese a ser necesario para `batch_watcher.py`.
5. **El polling de analytics no sobrevive al reinicio** del proceso.
7. **`README.md` está desactualizado**: no menciona Shorts, ACMI/TacView, debrief, guiones de narración,
   captions sociales, dashboard de Stats, watcher de lotes ni el bot de Discord.
8. **Acoplamiento a símbolo privado**: `youtube_uploader` usa `dcs_meta._memory_lock`.
9. **No hay CI ni linter ni medición de cobertura** configurados.

---

## 8. Requisitos del entorno

- Python 3.10 o superior (el código usa `str | None` y `list[str]` sin `from __future__`).
- `ffmpeg` y `ffprobe` en el `PATH`.
- `GEMINI_API_KEY` como variable de entorno.
- `config/client_secret.json` de Google Cloud Console, tipo *Desktop app*.
- Opcional: `watchdog` para el watcher de lotes; `discord.py` para el bot.
- En Linux, `zenity` para el selector de ficheros.
