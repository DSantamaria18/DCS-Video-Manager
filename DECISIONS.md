# DECISIONS.md — DCS Video Manager

Registro de decisiones técnicas y de proceso, con su motivo. Incluye las lecciones aprendidas de
errores pasados para no repetirlos.

**Cómo usar este fichero:**

- Antes de arrancar cualquier tarea, léelo entero (regla 10 de `CLAUDE.md`). Si detectas que vas a
  repetir un error ya registrado, párate y dilo.
- Cada entrada nueva va **arriba**, con fecha `AAAA-MM-DD`, contexto, decisión y consecuencia.
- Una decisión revertida no se borra: se marca como *Revertida* y se enlaza la entrada que la sustituye.

---

## Índice

- [Decisiones de proceso](#decisiones-de-proceso)
- [Decisiones técnicas](#decisiones-técnicas)
- [Lecciones aprendidas](#lecciones-aprendidas)

---

## Decisiones de proceso

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

## Decisiones técnicas

> Las entradas de esta sección se han **reconstruido leyendo el código de `main`**. Documentan el porqué
> aparente de decisiones ya tomadas, para que no se reviertan por accidente. Si alguna no refleja la
> intención original, corrígela.

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
