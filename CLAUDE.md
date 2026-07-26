# CLAUDE.md — DCS Video Manager

Instrucciones operativas para Claude Code en este repositorio. Léelas enteras antes de tu
primera acción en cada sesión.

---

## 1. Contexto del proyecto

Herramienta personal de David (canal de YouTube @TheCylonPilot) para automatizar la generación
de metadatos y la subida de vídeos de DCS World a YouTube.

**Stack real (verificado en el repo, no asumas otro):**

| Área | Tecnología |
|---|---|
| Lenguaje | Python 3.10+ |
| Web / UI | Flask (`web/app.py`) + `web/templates/index.html`, servidor local en `localhost:5000` |
| IA | Google Gemini Vision (`gemini-2.5-flash` por defecto, configurable) |
| Vídeo / imagen | ffmpeg (subproceso), Pillow |
| APIs Google | `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` (YouTube Data API v3, OAuth2 Desktop app) |
| Bot | `discord.py` (`discord_bot.py`) |
| Tests | pytest (`tests/`) |
| Rama principal | **`main`** |
| CI | **No existe todavía** (no hay `.github/workflows/`) |

**Entrypoints principales:** `dcs_meta.py` (motor de análisis + CLI batch), `youtube_uploader.py`
(subida OAuth2), `web/app.py` (servidor Flask), `batch_watcher.py`, `discord_bot.py`.

**Datos y secretos:** `config/config.json` (configuración de canal), `config/client_secret.json` y
`config/youtube_token.json` (**nunca se commitean**, están en `.gitignore`), `memory/history.json`
(últimos 50 vídeos analizados), `output/` (metadatos y miniaturas generados).

> **Nota sobre la rama:** todas las reglas de este documento dicen `main`. Si en algún encargo
> aparece `master`, se refiere a `main`. No crees una rama `master`.

---

## 2. Estilo de trabajo y de respuesta

Reglas de comportamiento base, aplicables a todos los agentes y a todas las respuestas:

- **Lee los ficheros existentes antes de escribir.** No los vuelvas a leer si no han cambiado.
- **Exhaustivo al razonar, conciso al responder.** El razonamiento largo va en el trabajo, no en el output.
- **Salta ficheros de más de 100 KB** salvo que sean imprescindibles para la tarea.
- **Sin aperturas aduladoras ni cierres de relleno.** Nada de "excelente pregunta" ni resúmenes
  redundantes al final.
- **Sin emojis ni rayas largas (em-dash).**
- **No adivines APIs, versiones, flags, SHAs de commit ni nombres de paquetes.** Verifica leyendo el
  código o la documentación oficial antes de afirmar nada. Si no lo has verificado, dilo
  explícitamente en lugar de afirmarlo.
- Comunicación en español.

---

## 3. Reglas de trabajo

1. **Documentación viva.** Actualiza estos ficheros en cada cambio relevante, no al final:
   - `README.md` — descripción y propósito general de la app.
   - `BACKLOG.md` — features o defectos pendientes: descripción breve, justificación, dificultad.
     Cuando algo se implementa, se mueve de aquí a `CHANGELOG.md`.
   - `CHANGELOG.md` — cambios de cada versión generada.
   - `FEATURES.md` — funcionalidades ya implementadas, con su descripción.
   - `DECISIONS.md` — decisiones tomadas durante el desarrollo y por qué, incluyendo lecciones
     aprendidas de errores pasados para no repetirlos.
   - `ARCHITECTURE.md` — arquitectura de la aplicación.
2. **Especificación antes de código.** Antes de escribir una sola línea de código redactamos juntos
   un documento de especificaciones (`SPEC.md`). No se avanza hasta que David lo apruebe explícitamente.
3. **Plan antes de implementar.** Antes de implementar cualquier feature, presenta a David un plan
   detallado de qué vas a hacer y cómo. No escribas código hasta que él lo confirme. Si no dice
   explícitamente algo como "adelante", **no hay luz verde**.
4. **Código limpio**, siguiendo principios SOLID.
5. **TDD.** Escribe el test antes que el código. Los tests verifican **comportamiento y contratos**,
   no detalles internos de implementación: un refactor interno que no cambia el comportamiento no
   debe romper tests.
6. **Comenta el porqué, no el qué.** Evita comentarios redundantes con el propio código.
7. **Seguridad.** Valida inputs, gestiona autenticación/autorización donde aplique, no expongas
   secretos ni datos sensibles, sigue buenas prácticas básicas de seguridad.
8. **Propón mejoras.** Además de lo que David pida, anota en `BACKLOG.md` las mejoras y funcionalidades
   nuevas que veas razonables, con su justificación. **No las implementes sin aprobación previa.**
9. **Paraleliza.** Para tareas paralelizables (features independientes, tests vs. implementación),
   lanza varios agentes en paralelo en vez de trabajar en serie, cuando tenga sentido.
10. **Revisa `DECISIONS.md` antes de arrancar cualquier tarea nueva** para no repetir errores ya
    identificados. Si detectas que vas a repetir uno, párate y dilo.
11. **Nada destructivo sin aprobación explícita** de David: borrado de datos, migraciones destructivas,
    sobrescritura sin backup, `force-push`, etc. Todo cambio debe poder revertirse: commits atómicos,
    ramas, y backup antes de operaciones sensibles.
12. **Una rama por feature/bug.**

---

## 4. Equipo de agentes y flujo de trabajo

Roles (Tech Lead, Developers, QA, TechOps), Definition of Done, reglas de PR/merge, worktrees y
llamadas a APIs de pago: ver `.claude/team-workflow.md`. Léelo antes de orquestar desarrollo
multi-agente (asignar tareas, revisar o mergear una PR); no hace falta para una consulta o bugfix
puntual de una sola sesión.

Deuda de infraestructura y documentación pendiente (CI, linter, coverage, E2E, etc.): ver
`BACKLOG.md`. Decisiones de proceso y lecciones aprendidas: ver `DECISIONS.md` (regla 10, lectura
completa obligatoria). Rationale de decisiones técnicas de código: `DECISIONS_TECHNICAL.md`, solo al
tocar el fichero/feature concreto que cita.
