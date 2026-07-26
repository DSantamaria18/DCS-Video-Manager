# BACKLOG — DCS Video Manager

> Última actualización: 2026-07-26

Features y defectos pendientes. Cuando algo se implementa, se mueve de aquí a `CHANGELOG.md`.

**Prioridad:** P0 crítico · P1 alto · P2 medio · P3 bajo
**Dificultad:** S (menos de medio día) · M (1–2 días) · L (más de 2 días o riesgo alto)

Todas las entradas de esta versión salen de una lectura del código de `main`. Cada una cita la evidencia.
Ninguna se implementa sin aprobación previa de David (regla 8).

---

## Seguridad

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| SEC-01 | `discord_bot_token` se guarda en un fichero rastreado por git | P0 | S | `config/config.json` **no** está en `.gitignore` y contiene las claves `discord_bot_token`, `discord_channel_id` y `discord_webhook_url`. La pestaña Setup escribe ahí (`_CONFIG_ALLOWED_KEYS` en `web/app.py`). Hoy los valores están vacíos, así que no hay filtración, pero en cuanto David introduzca el token el siguiente commit lo publica en un repositorio público. Es incoherente con el tratamiento de `GEMINI_API_KEY`, que solo se lee del entorno. Propuesta: mover los secretos a variables de entorno o a un `config/secrets.json` ignorado, y dejar en `config.json` solo configuración no sensible. |
| SEC-02 | Endpoints `POST` sin protección CSRF ni autenticación | P1 | M | Ningún endpoint de `web/app.py` valida origen ni token. El servidor escucha en `localhost:5000` mientras David navega con el mismo navegador: cualquier página abierta puede enviarle peticiones. Varios endpoints leen y escriben rutas arbitrarias del disco tomadas del payload (`video_path`, `acmi_path`) y `POST /api/config` reescribe la configuración. Propuesta: token CSRF por sesión o comprobación de cabecera `Origin`, más validación de que las rutas caen bajo directorios permitidos. |
| SEC-03 | Interpolación de cadenas en scripts de PowerShell y AppleScript | P2 | S | `_open_file_dialog()` construye el script inyectando `initial_dir` y `title` directamente en la cadena. El valor viene de `config/last_folder.txt`, no de la red, así que hoy el riesgo es bajo, pero el patrón se rompe en cuanto una ruta contenga comillas. Propuesta: pasar los valores como argumentos en lugar de interpolarlos. |
| SEC-04 | Tests de seguridad inexistentes | P2 | M | QA tiene asignada la implementación y mantenimiento de tests de seguridad y hoy no hay ninguno. Como mínimo: recorrido de rutas en los endpoints que aceptan paths, validación de entrada en `POST /api/config`, y comprobación de que ningún secreto termina en `output/` ni en los logs. |

---

## Infraestructura

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| INF-05 | El sondeo de analytics no sobrevive al reinicio | P2 | M | `schedule_analytics_polling()` usa cuatro `threading.Timer` daemon a 1 h, 6 h, 12 h y 24 h. Si la app se cierra antes, los sondeos pendientes se pierden sin dejar rastro. Propuesta: persistir los sondeos pendientes en `history.json` y reprogramarlos al arrancar. |
| INF-06 | Crear el primer tag de git al cortar versión | P2 | S | Decisión ya tomada (ver `DECISIONS.md`, pregunta 6 de `SPEC.md` respondida): tags `vMAYOR.MENOR.PARCHE` a partir de la próxima entrega. CI (INF-01) ya resuelto; bloqueado solo por SEC-01 — único requisito que queda listado en `CHANGELOG.md` para cortar la primera versión. |

---

## Deuda técnica

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| TEC-01 | `dcs_meta.py` es un monolito de ~2.200 líneas | P1 | L | Mezcla carga de configuración, I/O de ficheros, invocación de ffmpeg, cliente HTTP de Gemini, procesado de imagen con Pillow, parsing de TacView ACMI, reglas de SEO, generación de Shorts y una CLI. Viola la regla 4 (SOLID) y hace difícil escribir tests de comportamiento en lugar de tests de implementación. También reduce la separabilidad entre los 2 Developers: casi cualquier feature toca este fichero. Pregunta 4 de `SPEC.md` respondida (2026-07-26): incremental, dividido en TEC-01a–e, una PR por dominio, en orden de menor a mayor acoplamiento. `dcs_meta.py` reexporta cada símbolo movido para no romper los 47 call sites existentes en `web/app.py`, `discord_bot.py`, `batch_watcher.py` y `youtube_uploader.py`. |
| TEC-01a | Extraer `acmi/` de `dcs_meta.py` | P1 | S | `_parse_acmi_props`, `parse_acmi_events`. Sin dependencias de otros dominios del monolito: primer corte, más seguro, valida el patrón de reexport antes de tocar dominios con más acoplamiento. |
| TEC-01b | Extraer `thumbnail/` de `dcs_meta.py` | P1 | S | `_load_font`, `_fit_text`, `_score_frame`, `_grade_frame`, `_apply_thumbnail_overlay`, `_save_thumbnail`, `generate_thumbnail_on_demand`. Solo depende de Pillow y `config`, no de otros dominios. |
| TEC-01c | Extraer `media/` de `dcs_meta.py` | P1 | M | `_get_video_duration`, `_seconds_to_chapter_time`, `detect_audio_chapters`, `extract_frames`, `extract_obs_metadata`, `_parse_audio_peaks`, `_collect_candidate_timestamps`, `_deduplicate_candidates`, `detect_short_clips`, `generate_short_metadata`. Depende de `acmi/` (TEC-01a) para `detect_short_clips`. |
| TEC-01d | Extraer `gemini/` de `dcs_meta.py` | P1 | M | `build_prompt`, `call_gemini`, `generate_metadata`, `build_fallback_metadata`, `_recover_json`, `is_squadron_video`, `_detect_series`, `_aircraft_series_suggestions`, `_video_length_category`, `_build_description_rules`, `_build_module_guide`. Depende de `media/` (TEC-01c) para duración y extracción de frames. El dominio más central: último de los "solo consumidores", antes del que depende de él. |
| TEC-01e | Extraer `seo/` de `dcs_meta.py` | P1 | S | `check_description_seo`, `rewrite_description_seo`, `format_description`, `run_upload_checklist`. Depende de `gemini/` (TEC-01d): `rewrite_description_seo` llama a `call_gemini`. Último dominio, cierra TEC-01. |
| TEC-02 | `youtube_uploader` accede a `dcs_meta._memory_lock` | P2 | S | Uso de un símbolo privado de otro módulo desde `schedule_analytics_polling()`. Propuesta: exponer una función pública de escritura segura en `dcs_meta` (por ejemplo `append_analytics(video_id, filename, data)`) y que el uploader la llame. |
| TEC-03 | `processing_status` se muta desde varios hilos sin lock | P2 | S | El diccionario global de `web/app.py` lo escriben los hilos de análisis, subida y Shorts, y lo lee el endpoint de estado. Cada job usa su propia clave, lo que en CPython funciona en la práctica, pero no es una garantía explícita del diseño y `_evict_old_jobs()` sí itera y borra sobre el diccionario completo. Propuesta: proteger con un `threading.Lock`. |
| TEC-04 | Toda la UI en un único `index.html` | P3 | L | HTML, CSS y JavaScript conviven en un solo fichero sin build step. Es una decisión deliberada (ver `DECISIONS.md`) y aporta simplicidad de arranque, pero convierte cualquier PR de UI en un punto de conflicto garantizado entre Developers en paralelo. Revisar solo si el fichero se vuelve inmanejable. |

---

## Documentación

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |

Sin documentación pendiente ahora mismo.

---

## Features propuestas

Ideas del equipo, no pedidas por David. **No se implementan sin su aprobación** (regla 8).

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| FEA-01 | Reintento con backoff en las llamadas a Gemini | P2 | S | Hoy un fallo transitorio (rate limit, timeout) cae directamente al camino de `build_fallback_metadata()`, degradando la calidad del resultado por un error recuperable. Un reintento con espera exponencial ante `429` y `5xx` aprovecharía mejor la cuota diaria. |
| FEA-03 | Estimación de coste antes de analizar | P3 | S | La UI no indica cuántas llamadas a Gemini va a disparar una acción. Mostrar el número de frames y una estimación ayuda a decidir antes de gastar cuota, especialmente con `gemini-2.5-pro`. |
| FEA-05 | Validación de rutas contra directorios permitidos | P2 | S | Complemento de SEC-02: restringir `video_path` y `acmi_path` a `recordings_folder` y a la última carpeta usada, en lugar de aceptar cualquier ruta del sistema. |

---

## Bugs

| # | Título | Prioridad | Dif. | Descripción |
| --- | --- | --- | --- | --- |

Sin bugs confirmados. Los defectos potenciales detectados por lectura de código están en las secciones de
Seguridad y Deuda técnica; ninguno se ha reproducido en ejecución todavía.
