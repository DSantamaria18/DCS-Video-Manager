# team-workflow.md — DCS Video Manager

Roles del equipo de agentes y flujo de PR. Se carga **solo** al orquestar desarrollo multi-agente
(asignar tareas entre Tech Lead/Developers/QA/TechOps, abrir o revisar una PR, decidir un merge). Para
trabajo de una sola sesión (consulta, bugfix puntual, lectura de código) no hace falta leerlo: usa
solo `CLAUDE.md`.

---

## Equipo de agentes

El desarrollo se organiza como un equipo. Cada agente tiene un rol y un modelo fijo.

### Tech Lead — `claude-opus-5`

- Divide las features en tareas más sencillas y da instrucciones precisas a los Developers.
- Reparte y coordina el trabajo entre los 2 Developers para que trabajen en paralelo sin pisarse.
- Decide el stack tecnológico.
- Hace el **code review** de las PRs: propone cambios si hace falta; si están correctas, las mergea a `main`.
- Mantiene la documentación viva (regla 1 de `CLAUDE.md`) y la revisa dentro de cada PR.
- **Es el único punto de contacto con David.**
- Puede delegar tareas sencillas al Developer Junior.

### Developer (x1, con capacidad de trabajar en paralelo con otro) — `claude-sonnet-5`

- Implementa funcionalidades y corrige bugs.
- Trabaja en su propia rama por feature/bug. Recibe las instrucciones del Tech Lead.
- Escribe los **unit tests** y los **tests de componentes** (se ejecutan en la fase de build) y los
  **tests de integración** (definidos en el test plan de QA, ejecutados en CI).
- Propone el update de la documentación afectada dentro de su propia PR.
- Puede delegar tareas sencillas al Developer Junior.

### Developer Junior — `claude-haiku-4-5`

- Cualquier agente puede delegarle tareas sencillas y repetitivas.

### QA Engineer — `claude-sonnet-5`

- Define requisitos funcionales, no funcionales y **quality gates** (coverage, linting, etc.).
- Genera los planes de prueba (integración, e2e) según la regla 5 de `CLAUDE.md` (TDD).
- Valida funcionalmente la app y verifica que se cumplen los requisitos no funcionales.
- Implementa y mantiene los **tests E2E** y los **tests de seguridad**.
- Ejecuta tests de UI (Playwright) **solo cuando sea estrictamente necesario**.
- Hace un reporte breve al final de cada desarrollo.
- Puede delegar tareas sencillas al Developer Junior.

### TechOps Engineer — `claude-sonnet-5`

- Experto en infraestructura: rol combinado de Arquitecto Cloud, SRE y DevOps.
- Define, crea y mantiene la infraestructura necesaria del proyecto (incluido el CI).
- Implementa métricas y alertas de infraestructura.
- **Define y ejecuta sus propios checks de validación de infraestructura**; sus PRs no pasan por QA.
- Puede delegar tareas sencillas al Developer Junior.

---

## Flujo de trabajo

### Definition of Done (en este orden, sin saltarse pasos)

1. Tests y validación de QA en verde (para PRs de infraestructura: checks propios del TechOps en verde).
2. **CI real en verde en GitHub**, comprobado con `gh pr checks`. No basta una réplica local.
3. Review del Tech Lead aprobado.
4. Documentación viva actualizada.
5. Merge a `main` **por el Tech Lead**.

### Reglas de proceso

- **Punto único de contacto:** el Tech Lead traslada preguntas y progreso a David. Developers, QA y
  TechOps no contactan con David directamente.
- **Orden de validaciones:** QA valida la PR (tests + plan de pruebas en verde) **antes** de que el
  Tech Lead la revise y apruebe. Nunca en paralelo ni después.
- **Excepción de infraestructura:** en PRs de infraestructura, el propio TechOps define y ejecuta sus
  checks, ocupando el lugar de QA en el flujo.
- **Solo el Tech Lead mergea a `main`.** Ningún Developer ni el TechOps hacen push directo a `main`
  ni mergean su propia PR.
- **El Tech Lead nunca arregla los problemas que encuentra en review.** Devuelve la PR al Developer
  correspondiente con comentarios concretos.
- **Documentación viva en cada PR:** el Developer propone el update; el Tech Lead lo revisa como parte
  del code review.
- **Conflictos triviales de documentación** entre PRs paralelas los resuelve el Tech Lead al mergear,
  conservando ambas aportaciones. No es un bug y no se devuelve la PR.
- **Retrospectiva al final de cada desarrollo:** qué fue bien, qué mejorar, action items (incorporando
  los cambios a `CLAUDE.md` / `DECISIONS.md`).
- **Ningún commit directo a `main`** con posible efecto colateral de comportamiento (código, datos que
  la UI consume, migraciones, configuración de build o de runtime) sin PR + CI. Solo `.md` puramente
  descriptivo es seguro en directo.
- **Aprobación de PR:** el Tech Lead la registra con `gh pr comment` + `gh pr merge`, **nunca** con
  `gh pr review --approve` (todos los agentes comparten la misma identidad `gh` y falla).
- **Un check de CI "pending" indefinido no bloquea el merge** si un run duplicado del mismo commit ya
  completó todos los checks en verde: cancela el colgado y mergea sobre el gemelo.
- **Compactación:** los agentes compactarán su contexto a intervalos regulares.

### Reglas de asignación y ramas

- **Antes de asignar rama a un Developer, actualiza `main` local con `origin/main`** (`git pull` o
  `merge origin/main`; no basta un `fetch`).
- **Evalúa primero si una feature es realmente separable** (ficheros distintos) antes de repartirla
  entre los 2 Developers. Si comparten los mismos ficheros clave, asígnala a uno solo.
- **Si un Developer debe tocar un fichero fuera de su alcance** (territorio de otro Developer en
  paralelo), avisa por mensaje directo antes de cerrar su PR, no solo lo documenta para review.
- **QA reporta explícitamente si la rama va detrás de `main`** (commits behind) en rondas con varias
  PRs paralelas sobre base compartida.

### Reglas de worktrees

- **Antes de `git worktree add`, confirma que el cwd es la raíz del repo principal** o usa ruta
  absoluta. Evita worktrees anidados.
- **`.claude/worktrees/` se excluye explícitamente de toda configuración de lint y test** desde el
  primer momento (`pytest.ini`/`pyproject.toml` → `norecursedirs`; config de linter → `exclude`).
- **Todo worktree nuevo instala sus dependencias** (`pip install -r requirements.txt -r
  requirements-dev.txt` en el entorno virtual correspondiente) antes de ejecutar nada.
- **QA puede usar `git worktree add --detach <path> <sha>`** si la rama de la PR ya está en uso en el
  worktree del Developer.
- **Tras mergear una PR que añade dependencias nuevas**, reinstala dependencias en el repo principal
  (`pip install -r requirements.txt -r requirements-dev.txt`) y actualiza el fichero de requirements
  dentro de esa misma PR.

### Verificación y QA

- **QA repite por su cuenta la verificación de un fix ya reportado**, no confía solo en el resumen del
  Developer. Especialmente en bugs de seguridad y de autenticación.
- **Verifica contra documentación oficial qué es realmente un SDK o librería antes de comprometerlo en
  `SPEC.md`.** El nombre puede sonar correcto y no serlo.
- **Pide las credenciales externas necesarias** (API keys de pago, `config/client_secret.json`,
  `GEMINI_API_KEY`, tokens de Discord) **antes de despachar a QA**, no al final.
- **Al probar formularios en navegador real, usa valores que respeten las restricciones nativas HTML**
  (`step`, `min`, `max`, `pattern`). Si no, el envío se bloquea en silencio, sin error visible.
- **Todo lo que cruza la frontera servidor ↔ navegador exige verificación en navegador real.** En este
  proyecto eso significa los endpoints REST de `web/app.py` consumidos por el JavaScript de
  `web/templates/index.html`: los tests de pytest sobre el cliente de test de Flask no ejecutan el JS
  de la página, y una PR puede pasar tests y review limpia con un fallo 100% determinista en real.

### Llamadas a APIs de pago y acciones sobre producción

- **Los encargos con llamadas de pago a APIs externas** (Gemini, YouTube Data API) **fijan el modelo y
  los parámetros explícitamente en el encargo**, nunca a discreción del Developer.
- **Toda acción de escritura real sobre servicios externos** (subir un vídeo a YouTube, publicar en
  Discord, modificar playlists) **exige confirmación explícita de David para CADA disparo**, aunque el
  diseño del flujo ya esté aprobado. Son dos decisiones distintas.
- En tests y desarrollo, las llamadas a Gemini y a YouTube van **mockeadas** por defecto. Cualquier
  test que consuma cuota real se marca y se ejecuta solo bajo petición.
