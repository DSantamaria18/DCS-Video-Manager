# DECISIONS.md — DCS Video Manager

Registro de decisiones de proceso y lecciones aprendidas de errores pasados, para no repetirlos.
Rationale de decisiones técnicas de código: sección al final de este mismo fichero.

**Cómo usar este fichero:**

- Antes de arrancar cualquier tarea, léelo entero (regla 10 de `CLAUDE.md`). Si detectas que vas a
  repetir un error ya registrado, párate y dilo.
- Cada entrada nueva va **arriba**, con fecha `AAAA-MM-DD`, contexto, decisión y consecuencia.
- Una decisión revertida no se borra: se marca como *Revertida* y se enlaza la entrada que la sustituye.

---

## Índice

- [Decisiones de proceso](#decisiones-de-proceso)
- [Lecciones aprendidas](#lecciones-aprendidas)
- [Decisiones técnicas de código](#decisiones-técnicas-de-código) — consulta solo al tocar el
  fichero/feature concreto, no hace falta leerla entera al arrancar tarea

---

## Decisiones de proceso

### 2026-07-28 — SEC-01: fichero `secrets.json` separado, no variables de entorno

**Contexto.** `discord_webhook_url`, `discord_bot_token` y `discord_channel_id` vivían en
`config/config.json`, rastreado por git y sin entrada en `.gitignore`. A diferencia de
`GEMINI_API_KEY` (solo se lee de entorno, sin campo en la UI), estos tres campos sí son editables
desde la pestaña Setup vía `POST /api/config` (`web/templates/index.html`).

**Decisión.** Se descarta el patrón de `GEMINI_API_KEY` (variable de entorno pura) porque exigiría
reiniciar el proceso para cambiar el token y rompería la UX de Setup ya existente. En su lugar,
los tres campos se mueven a `config/secrets.json`, nuevo fichero gitignoreado. `dcs_meta.load_config()`
fusiona `config.json` + `secrets.json` de forma transparente (mismo dict de siempre para el resto del
código); `save_config()` en `web/app.py` separa qué claves van a cada fichero al escribir.
`discord_bot.py`, que no importa `dcs_meta`, replica el mismo merge con su propia constante
`SECRETS_PATH` para no perder su carácter de script standalone.

**Consecuencia.** `config/config.json` tracked ya no puede filtrar un secreto aunque David rellene
los campos desde la UI. Bloqueante de INF-06 (primer tag de versión) resuelto. Lección para el
futuro: al añadir un nuevo secreto editable desde la UI, va a `secrets.json`, no a `config.json`.

### 2026-07-26 — CI real en GitHub Actions, ruff no bloqueante hasta limpiar deuda

**Contexto.** INF-01. `ruff check .` detectó 129 issues preexistentes en el código (ver decisión de
elegir `ruff`, más abajo). La pregunta 2 de `SPEC.md` decía que ruff bloquea desde el primer CI, pero
eso dejaría el CI en rojo desde el día 1 para cualquier PR.

**Decisión.** `.github/workflows/ci.yml` corre en Python 3.10 (sin matriz, único soporte declarado hoy).
`ruff check .` se ejecuta con `|| true` (reporta, no bloquea el job). `pytest -q` sí bloquea, con
coverage reportado vía `pytest-cov` (sin `--cov-fail-under`, regla ya tomada).

**Consecuencia.** Se abre ítem en `BACKLOG.md` para limpiar las 129 issues; cuando lleguen a cero, se
quita el `|| true` y ruff pasa a bloqueante, cumpliendo la intención original de la pregunta 2.

### 2026-07-26 — TEC-05: cierre de deuda de ruff, `except Exception` deliberado documentado con `noqa`

**Contexto.** Al cerrar las 129 issues, 37 eran `BLE001` (blind-except). No todas son iguales: en
`dcs_meta.py` los `except Exception` envuelven llamadas a `_get_video_duration()`/`call_gemini()`,
funciones propias cuyo código se pudo leer entero para saber exactamente qué excepciones lanzan
(`RuntimeError`, `subprocess.CalledProcessError`, `json.JSONDecodeError`, `KeyError`, `ValueError` /
`OSError`) — ahí se hizo narrowing real. En `web/app.py` (frontera HTTP: cada endpoint debe devolver
un 500 en vez de tumbar el proceso Flask) y en `youtube_uploader.py` (superficie de
`googleapiclient`/`google-auth-oauthlib`, no verificable sin credenciales reales contra la API), el
`except Exception` amplio es la frontera de error correcta por diseño, no deuda.

**Decisión.** Regla del proyecto (CLAUDE.md): "no adivines APIs... si no lo has verificado, dilo
explícitamente". Adivinar los tipos de excepción exactos de `googleapiclient` sin poder probarlos
contra la API real habría sido peor que dejar el `except Exception` — narrowing mal hecho puede dejar
un fallo real sin capturar. Se documentó cada caso con `# noqa: BLE001` y un comentario del porqué, en
vez de narrowing especulativo. Mismo criterio para los 4 `datetime.now()` sin tzinfo (`DTZ005`):
son timestamps de nombre de fichero/log en hora local de la máquina, intencional — no se persisten ni
se comparan entre zonas horarias, así que forzar UTC habría sido un cambio de comportamiento visible
para David sin que nadie lo pidiera.

**Consecuencia.** `ruff check .` = 0 issues reales, sin narrowing forzado en superficie externa no
verificable. Si algún día se añaden tests contra la API real de YouTube, revisar si esos `noqa` pueden
convertirse en narrowing real.

### 2026-07-26 — Linter `ruff` y coverage `pytest-cov`, sin umbral bloqueante

**Contexto.** Preguntas 2 y 3 de `SPEC.md`. `requirements-dev.txt` solo tenía `pytest`; no había
herramienta de linting ni de coverage declarada.

**Decisión.** `ruff` como linter (`ruff.toml`, excluye `.claude/worktrees`, cierra INF-04) y
`pytest-cov` para coverage (`--cov-report=term-missing` en `pytest.ini`, sin `--cov-fail-under`: se mide
y reporta, no bloquea el build).

**Evidencia de la elección.** Verificado contra PyPI (`pip index versions`): `ruff` 0.16.0, `pytest-cov`
7.1.0, ambos vigentes al fijar la versión en `requirements-dev.txt`.

**Consecuencia.** El CI (INF-01, aún sin implementar) debe correr pytest + ruff + coverage, los tres
bloqueantes salvo el umbral de coverage, que no bloquea.

### 2026-07-26 — Versionado con tags de git a partir de la próxima entrega

**Contexto.** Pregunta 6 de `SPEC.md`. `CHANGELOG.md` ya sigue SemVer y arranca en `[No publicado]`,
pero ninguna versión tiene tag de git.

**Decisión.** Cada release se etiqueta con `vMAYOR.MENOR.PARCHE` en git, además de su entrada en
`CHANGELOG.md`.

**Consecuencia.** La primera etiqueta espera a que INF-01 (CI) y SEC-01 (`discord_bot_token` en
`config.json`) estén resueltos — son los bloqueantes ya listados en `CHANGELOG.md` para cortar la
primera versión. No se crea tag hasta entonces.

### 2026-07-26 — Adoptar el modelo de equipo de agentes y crear `CLAUDE.md`

**Contexto.** El desarrollo pasa a hacerse con un equipo de agentes (Tech Lead, 2 Developers, Developer
Junior, QA Engineer, TechOps Engineer) en lugar de un único agente generalista.

**Decisión.** Se crea `CLAUDE.md` como fuente única de las reglas de trabajo, los roles, el flujo de PR y
la Definition of Done. Todos los agentes lo leen antes de su primera acción en cada sesión.

**Consecuencias.**

- El Tech Lead es el único punto de contacto con David.
- Solo el Tech Lead mergea a `main`.
- El orden de validación es fijo: QA → Tech Lead → merge. Nunca en paralelo.
- Las PRs de infraestructura sustituyen la validación de QA por los checks propios del TechOps.

### 2026-07-26 — La rama principal es `main`, no `master`

**Contexto.** Las reglas de proceso heredadas de otro proyecto hablaban de `master`. El repositorio real
usa `main`.

**Decisión.** Toda la documentación y todos los encargos usan `main`. No se crea ninguna rama `master`.

**Consecuencia.** Si un encargo menciona `master`, se interpreta como `main` sin preguntar.

### 2026-07-26 — Registrar la aprobación de PR con `gh pr comment` + `gh pr merge`

**Contexto.** Todos los agentes comparten la misma identidad de `gh`, así que `gh pr review --approve`
falla al intentar aprobar una PR creada por esa misma identidad.

**Decisión.** El Tech Lead deja constancia de la aprobación con `gh pr comment` y después ejecuta
`gh pr merge`.

### 2026-07-26 — La documentación viva se actualiza dentro de la PR, no después

**Contexto.** Documentar al final produce documentación que nadie revisa y que diverge del código.

**Decisión.** El Developer propone el update de `README.md`, `FEATURES.md`, `CHANGELOG.md`, `BACKLOG.md`,
`ARCHITECTURE.md` y `DECISIONS.md` dentro de su propia PR. El Tech Lead lo revisa como parte del code
review. Los conflictos triviales de documentación entre PRs paralelas los resuelve el Tech Lead al
mergear, conservando ambas aportaciones: no es un bug y no se devuelve la PR.

---

## Lecciones aprendidas

Errores ya cometidos. Cada agente debe comprobar esta lista antes de arrancar una tarea.

### Verificación y testing

- **Los tests verdes no cubren la frontera servidor ↔ navegador.** El cliente de test de Flask no ejecuta
  el JavaScript de `index.html`. Un cambio en la forma de un payload puede pasar tests y code review
  limpios y romper la UI de forma 100% determinista en real. Todo cambio que cruce esa frontera exige
  verificación en navegador.
- **QA repite por su cuenta la verificación de un fix ya reportado.** No basta el resumen del Developer,
  especialmente en bugs de seguridad y de autenticación.
- **Al probar formularios en navegador real, usa valores que respeten las restricciones HTML nativas**
  (`step`, `min`, `max`, `pattern`). Si no, el envío se bloquea en silencio, sin error visible. En este
  proyecto afecta como mínimo a `frames_to_extract` (1–20) y a `window_minutes` (1–30).
- **Pide las credenciales externas antes de despachar a QA**, no al final: `GEMINI_API_KEY`,
  `config/client_secret.json`, token del bot de Discord. Descubrir que faltan al final invalida la ronda
  de pruebas.

### Coordinación

- **Evalúa si una feature es realmente separable** (ficheros distintos) antes de repartirla entre los 2
  Developers. Si comparten los mismos ficheros clave, asígnala a uno solo. En este repo casi todo pasa por
  `dcs_meta.py`, `web/app.py` o `index.html`, así que la separabilidad real es baja: comprueba siempre.
- **Si un Developer debe tocar un fichero fuera de su alcance**, avisa por mensaje directo antes de cerrar
  su PR. No basta con documentarlo para el review.
- **Antes de asignar rama, actualiza `main` local con `origin/main`.** Un `fetch` no es suficiente.
- **QA reporta explícitamente si la rama va detrás de `main`** (commits behind) cuando hay varias PRs
  paralelas sobre base compartida.

### Git y worktrees

- **Antes de `git worktree add`, confirma que el cwd es la raíz del repo principal**, o usa ruta absoluta.
  Evita worktrees anidados.
- **`.claude/worktrees/` se excluye de toda configuración de lint y test desde el primer momento**
  (`norecursedirs` en la config de pytest, `exclude` en la del linter).
- **QA puede usar `git worktree add --detach <path> <sha>`** si la rama de la PR ya está ocupada en el
  worktree del Developer.
- **Todo worktree nuevo instala sus dependencias** antes de ejecutar nada.
- **Tras mergear una PR con dependencias nuevas, reinstala en el repo principal.**
- **Ningún commit directo a `main`** con posible efecto colateral de comportamiento (código, datos que la
  UI consume, configuración de build o de runtime) sin PR + CI. Solo `.md` puramente descriptivo es seguro
  en directo.

### CI

- **Comprueba el CI real con `gh pr checks`**, no una réplica local. Una réplica local en verde no cierra
  el paso 2 de la Definition of Done.
- **Un check "pending" indefinido no bloquea el merge** si un run duplicado del mismo commit ya completó
  todos los checks en verde: cancela el colgado y mergea sobre el gemelo.

### Coste y APIs externas

- **Los encargos con llamadas de pago fijan el modelo y los parámetros explícitamente**, nunca a
  discreción del Developer. Aplica a Gemini y a la YouTube Data API, cuya cuota diaria es limitada.
- **En tests y desarrollo, las llamadas a Gemini y a YouTube van mockeadas por defecto.** Cualquier test
  que consuma cuota real se marca y solo se ejecuta bajo petición.
- **Verifica contra documentación oficial qué es realmente un SDK o librería antes de comprometerlo en
  `SPEC.md`.** El nombre puede sonar correcto y no serlo.

---

## Decisiones técnicas de código

Rationale de decisiones técnicas ya tomadas. Consulta esta sección solo cuando la tarea toca el fichero o feature concreto que cita cada entrada — no hace falta leerla entera al arrancar cualquier tarea.

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
