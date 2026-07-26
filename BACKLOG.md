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
| INF-01 | No existe pipeline de CI | P0 | M | No hay `.github/workflows/`. El paso 2 de la Definition of Done (`gh pr checks` en verde) es hoy incumplible, así que ninguna PR puede cerrarse correctamente. Primera tarea del TechOps Engineer. Debe ejecutar como mínimo pytest sobre las versiones de Python soportadas. |
| INF-02 | `watchdog` no está declarado en `requirements.txt` | P1 | S | `batch_watcher.py` lo importa y lanza `RuntimeError` si falta. `FEATURES.md` lo describe como "opcional", pero el endpoint `POST /api/batch/start` está expuesto en la UI sin avisar de la dependencia. Propuesta: declararlo como extra explícito o incluirlo en `requirements.txt`. |
| INF-03 | Sin linter ni medición de cobertura | P1 | S | `requirements-dev.txt` solo contiene `pytest`. QA no puede definir quality gates de linting ni de coverage sobre herramientas que no existen. Depende de que David fije el umbral (ver `SPEC.md`, pregunta 3). |
| INF-04 | Excluir `.claude/worktrees/` de la configuración de lint y test | P1 | S | Requisito de proceso de `CLAUDE.md`: debe estar excluido desde el primer momento, antes de que existan worktrees. Se implementa junto a INF-01 e INF-03 (`norecursedirs` en la config de pytest, `exclude` en la del linter). |
| INF-05 | El sondeo de analytics no sobrevive al reinicio | P2 | M | `schedule_analytics_polling()` usa cuatro `threading.Timer` daemon a 1 h, 6 h, 12 h y 24 h. Si la app se cierra antes, los sondeos pendientes se pierden sin dejar rastro. Propuesta: persistir los sondeos pendientes en `history.json` y reprogramarlos al arrancar. |
| INF-06 | Sin gestión de versiones ni tags de release | P3 | S | No hay versión declarada en ningún sitio. `CHANGELOG.md` arranca con un `0.1.0` de referencia que no corresponde a ningún tag. Depende de la pregunta 6 de `SPEC.md`. |

---

## Deuda técnica

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| TEC-01 | `dcs_meta.py` es un monolito de ~2.200 líneas | P1 | L | Mezcla carga de configuración, I/O de ficheros, invocación de ffmpeg, cliente HTTP de Gemini, procesado de imagen con Pillow, parsing de TacView ACMI, reglas de SEO, generación de Shorts y una CLI. Viola la regla 4 (SOLID) y hace difícil escribir tests de comportamiento en lugar de tests de implementación. También reduce la separabilidad entre los 2 Developers: casi cualquier feature toca este fichero. Propuesta: extraer por dominios (`gemini/`, `media/`, `acmi/`, `seo/`, `thumbnail/`) de forma incremental, una PR por dominio. Depende de la pregunta 4 de `SPEC.md`. |
| TEC-02 | `youtube_uploader` accede a `dcs_meta._memory_lock` | P2 | S | Uso de un símbolo privado de otro módulo desde `schedule_analytics_polling()`. Propuesta: exponer una función pública de escritura segura en `dcs_meta` (por ejemplo `append_analytics(video_id, filename, data)`) y que el uploader la llame. |
| TEC-03 | `processing_status` se muta desde varios hilos sin lock | P2 | S | El diccionario global de `web/app.py` lo escriben los hilos de análisis, subida y Shorts, y lo lee el endpoint de estado. Cada job usa su propia clave, lo que en CPython funciona en la práctica, pero no es una garantía explícita del diseño y `_evict_old_jobs()` sí itera y borra sobre el diccionario completo. Propuesta: proteger con un `threading.Lock`. |
| TEC-04 | Toda la UI en un único `index.html` | P3 | L | HTML, CSS y JavaScript conviven en un solo fichero sin build step. Es una decisión deliberada (ver `DECISIONS.md`) y aporta simplicidad de arranque, pero convierte cualquier PR de UI en un punto de conflicto garantizado entre Developers en paralelo. Revisar solo si el fichero se vuelve inmanejable. |

---

## Documentación

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| DOC-01 | `README.md` desactualizado | P1 | S | No menciona YouTube Shorts, TacView ACMI, el debrief de misión, los guiones de narración, las captions sociales, la pestaña Stats, el watcher de lotes, la publicación programada ni el bot de Discord. Tampoco documenta `discord_bot.py` pese a que `discord.py` es dependencia de producción. Un lector del README se forma una idea equivocada de lo que hace la app. |
| DOC-02 | `FEATURES.md` documenta features por número de issue sin trazabilidad | P3 | S | Las entradas citan `(#30, #43)`, `(#49)`, etc., pero no hay issues en el repositorio a los que apunten. Propuesta: decidir si se abren issues reales o si se sustituyen las referencias por identificadores del backlog. |

**Hecho (2026-07-26):** split de `CLAUDE.md` y `DECISIONS.md` para bajar el coste de tokens fijo por
sesión/tarea (~52% menos combinado). Roles/DoD/flujo de PR → `.claude/team-workflow.md` (solo se lee al
orquestar multi-agente). Rationale de decisiones técnicas de código → `DECISIONS_TECHNICAL.md` (solo al
tocar el fichero/feature concreto). §6 de `CLAUDE.md` eliminada por redundante con este fichero y con
`DECISIONS.md`.

---

## Features propuestas

Ideas del equipo, no pedidas por David. **No se implementan sin su aprobación** (regla 8).

| # | Título | Prioridad | Dif. | Descripción y justificación |
| --- | --- | --- | --- | --- |
| FEA-01 | Reintento con backoff en las llamadas a Gemini | P2 | S | Hoy un fallo transitorio (rate limit, timeout) cae directamente al camino de `build_fallback_metadata()`, degradando la calidad del resultado por un error recuperable. Un reintento con espera exponencial ante `429` y `5xx` aprovecharía mejor la cuota diaria. |
| FEA-02 | Caché de análisis por hash de fichero | P2 | M | Reanalizar el mismo vídeo vuelve a extraer frames y a gastar cuota de Gemini. Cachear el resultado indexado por hash o por (tamaño, mtime) ahorra coste y tiempo en las iteraciones de edición de metadatos. |
| FEA-03 | Estimación de coste antes de analizar | P3 | S | La UI no indica cuántas llamadas a Gemini va a disparar una acción. Mostrar el número de frames y una estimación ayuda a decidir antes de gastar cuota, especialmente con `gemini-2.5-pro`. |
| FEA-04 | Modo de simulación para desarrollo | P2 | M | Un flag de entorno que devuelva metadatos de ejemplo sin llamar a Gemini ni a YouTube permitiría a los agentes y a QA validar el flujo completo de la UI sin consumir cuota ni credenciales reales. Encaja con la regla de mockear por defecto recogida en `DECISIONS.md`. |
| FEA-05 | Validación de rutas contra directorios permitidos | P2 | S | Complemento de SEC-02: restringir `video_path` y `acmi_path` a `recordings_folder` y a la última carpeta usada, en lugar de aceptar cualquier ruta del sistema. |

---

## Bugs

| # | Título | Prioridad | Dif. | Descripción |
| --- | --- | --- | --- | --- |

Sin bugs confirmados. Los defectos potenciales detectados por lectura de código están en las secciones de
Seguridad y Deuda técnica; ninguno se ha reproducido en ejecución todavía.
