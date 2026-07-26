# DECISIONS_TECHNICAL.md — DCS Video Manager

Rationale de decisiones técnicas ya tomadas, reconstruido leyendo el código de `main`. Documenta el
porqué aparente para que no se reviertan por accidente.

**Cómo usar este fichero:** consúltalo solo cuando la tarea toca el fichero o feature concreto que
cita cada entrada — no hace falta leerlo entero al arrancar cualquier tarea (a diferencia de
`DECISIONS.md`, ver regla 10 de `CLAUDE.md`). Si alguna entrada no refleja la intención original,
corrígela.

---

### Llamar a la API REST de Gemini con `urllib.request` en lugar del SDK

**Evidencia.** `dcs_meta.py::call_gemini()` construye la petición HTTP a mano.

**Motivo aparente.** Mantener el árbol de dependencias mínimo: no hay ningún paquete de Google
específico de Gemini en `requirements.txt`, solo los de la API de YouTube.

**Consecuencia.** El manejo de errores y el parseo de la respuesta son responsabilidad del proyecto. De
ahí `_recover_json()`, que rescata respuestas envueltas en markdown o con JSON truncado.

**Antes de cambiarlo:** verifica contra documentación oficial qué SDK es realmente el correcto y qué
garantías aporta. Un nombre de paquete que suena bien puede no ser el que crees.

### Credenciales OAuth2 de tipo *Desktop app* en lugar de *Web application*

**Evidencia.** `youtube_uploader.py` usa `InstalledAppFlow.run_local_server(port=0)`.

**Motivo.** Evita tener que registrar y mantener URIs de redirección en Google Cloud Console. El puerto
efímero elimina los conflictos con el 5000 de Flask.

### Subida siempre como `private`, con `publishAt` opcional

**Evidencia.** `upload_video()` fuerza `effective_privacy = "private"` cuando hay `publish_at`, y la UI
llama siempre con `privacy="private"`.

**Motivo.** Ningún vídeo se hace público sin que David lo revise. La publicación programada se delega a
YouTube en lugar de mantener un scheduler propio.

**Regla derivada.** Toda acción de escritura real sobre servicios externos (subir un vídeo, publicar en
Discord, tocar playlists) exige confirmación explícita de David **para cada disparo**, aunque el diseño
del flujo ya esté aprobado. Son dos decisiones distintas.

### Reintento sin tags ante `invalidTags`

**Evidencia.** `upload_video()` captura la excepción, comprueba `"invalidTags" in str(e)` y reintenta con
`tags: []`.

**Motivo.** Google no permite fijar tags vía API a aplicaciones que no han pasado verificación. Es un
límite permanente del modo *Testing* de OAuth, **no un problema de scopes**. Perder los tags es preferible
a perder la subida.

**No hacer.** No intentes arreglarlo añadiendo scopes: no es la causa.

### Metadatos de respaldo cuando Gemini falla

**Evidencia.** `build_fallback_metadata()` y el bloque `try/except` en `POST /api/analyze`.

**Motivo.** Una cuota agotada o un timeout no deben bloquear la publicación. Se deriva un título del
nombre de fichero y del contexto, se aplica la plantilla genérica y la UI avisa en ámbar de que hay que
editar antes de subir.

### `GEMINI_API_KEY` solo desde variable de entorno

**Evidencia.** `POST /api/analyze` comprueba `os.environ.get("GEMINI_API_KEY")`. La clave no aparece en
`config.json` ni en la pestaña Setup.

**Motivo.** `config/config.json` está rastreado en git; el entorno no. Mantener la clave fuera del fichero
la mantiene fuera del repositorio.

**Contradicción abierta.** `discord_bot_token` **sí** se guarda en `config/config.json`, que sí está
rastreado. Es una inconsistencia de diseño pendiente de resolver (ver `BACKLOG.md`, SEC-01).

### Semántica de *merge* en `description_templates`

**Evidencia.** `POST /api/config` fusiona las claves entrantes con las existentes en lugar de sustituir el
diccionario completo, y valida cada clave contra `dcs_meta.VALID_TEMPLATE_KEYS`.

**Motivo.** Guardar una sola plantilla desde la UI no debe borrar las otras cinco. Una cadena vacía es un
valor válido: significa "resetear a la plantilla por defecto".

### Estado de trabajos en memoria, acotado a 50 entradas

**Evidencia.** `processing_status` y `_evict_old_jobs()` en `web/app.py`.

**Motivo.** La app es local y monousuario; persistir los jobs no aporta. El límite evita que un uso
prolongado consuma memoria sin control.

**Consecuencia aceptada.** Reiniciar la app pierde los trabajos en curso.

### Ventanas fijas para detectar clips de Shorts, sin tope de clips

**Evidencia.** `detect_short_clips()` divide el vídeo en ventanas de duración configurable (5 min por
defecto) y elige un evento por ventana según prioridad: kill → eyección → bomba guiada → SAM → BVR;
si no hay evento ACMI, el pico de audio más alto; si tampoco, el punto medio de la ventana.

**Motivo.** Reparto uniforme a lo largo del vídeo. Un tope global de clips concentraba los resultados en
los primeros minutos.

### La UI es un único fichero sin build step

**Evidencia.** `web/templates/index.html` contiene HTML, CSS y JavaScript.

**Motivo.** Sin Node ni bundler, la app arranca con `python web/app.py` y nada más.

**Consecuencia.** No hay tests de componentes de frontend en el sentido habitual. La validación del
JavaScript exige navegador real.

### Extracción incremental de `dcs_meta.py` por dominios (TEC-01), un módulo plano por PR

**Evidencia.** `acmi.py` (TEC-01a) extrae `_parse_acmi_props`/`parse_acmi_events` de `dcs_meta.py`.
`dcs_meta.py` termina con `from acmi import _parse_acmi_props, parse_acmi_events  # noqa: F401`.

**Motivo.** `BACKLOG.md` (TEC-01) proponía subcarpetas por dominio (`acmi/`, `media/`, etc.); se optó
por módulos planos (`acmi.py`) en la raíz, igual que `dcs_meta.py`/`youtube_uploader.py`/
`discord_bot.py`, porque cada dominio de este primer corte cabe en un único fichero y un paquete con
`__init__.py` no aporta nada aquí. `dcs_meta.py` reexporta cada símbolo movido para que los 47 call
sites existentes (`web/app.py`, `discord_bot.py`, `batch_watcher.py`, `youtube_uploader.py`), todos
como `dcs_meta.X`, sigan funcionando sin cambios en cada PR del refactor.

**Consecuencia.** `parse_acmi_events()` necesita `_seconds_to_chapter_time()`, que sigue en
`dcs_meta.py` hasta TEC-01c (dominio `media`). Para no crear un import circular a nivel de módulo
(`dcs_meta` → `acmi` → `dcs_meta`), el import de `_seconds_to_chapter_time` dentro de `acmi.py` es
diferido (dentro de la función, no a nivel de módulo). Desaparece en TEC-01c cuando esa función se
mueva también fuera de `dcs_meta.py`. Mismo patrón en `thumbnail.py` (TEC-01b) para `OUTPUT_PATH`,
`_get_video_duration` y `_DURATION_ERRORS`, todavía en `dcs_meta.py`.
