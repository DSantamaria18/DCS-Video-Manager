# DECISIONS.md — DCS Video Manager

Registro de decisiones de proceso y lecciones aprendidas de errores pasados, para no repetirlos.
Rationale de decisiones técnicas de código: `DECISIONS_TECHNICAL.md`.

**Cómo usar este fichero:**

- Antes de arrancar cualquier tarea, léelo entero (regla 10 de `CLAUDE.md`). Si detectas que vas a
  repetir un error ya registrado, párate y dilo.
- Cada entrada nueva va **arriba**, con fecha `AAAA-MM-DD`, contexto, decisión y consecuencia.
- Una decisión revertida no se borra: se marca como *Revertida* y se enlaza la entrada que la sustituye.

---

## Índice

- [Decisiones de proceso](#decisiones-de-proceso)
- [Lecciones aprendidas](#lecciones-aprendidas)
- Decisiones técnicas (rationale de código): `DECISIONS_TECHNICAL.md` — consulta solo al tocar el
  fichero/feature concreto, no hace falta leerlo entero al arrancar tarea

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
