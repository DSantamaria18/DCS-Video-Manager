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
