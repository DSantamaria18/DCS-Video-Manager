# CLAUDE.md — DCS Video Manager

Instrucciones operativas para Claude Code en este repositorio. Léelas enteras antes de tu
primera acción en cada sesión. Este documento asume **un único desarrollador (David) y un único
agente Claude por sesión** — sin equipo de agentes, sin roles, sin PRs internas. El objetivo
explícito es maximizar la eficiencia de tokens: cuenta básica de Claude, un solo usuario.

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

## 2. Eficiencia de tokens (prioridad operativa)

Cuenta básica, un único agente por sesión. Antes de escribir o modificar código, sube por esta
escalera y párate en el primer peldaño que resuelva el problema:

1. **¿Hace falta construir esto?** Si no lo ha pedido David ni es un requisito real, no lo hagas (YAGNI).
2. **¿Ya existe en este repo?** Reutiliza helpers, utilidades o patrones ya presentes en `dcs_meta.py`,
   `web/app.py`, etc. antes de escribir algo nuevo.
3. **¿Lo resuelve la stdlib de Python?** Úsala.
4. **¿Lo resuelve una dependencia ya instalada** (`requirements.txt` / `requirements-dev.txt`)? Úsala
   antes de añadir una nueva.
5. **¿Se puede resolver en una línea?** Hazlo en una línea.
6. Solo entonces: escribe el mínimo código que funcione.

Reglas derivadas:

- **Sin abstracciones no pedidas, sin dependencias nuevas si se puede evitar, sin boilerplate que
  nadie ha pedido.** Borrar código es preferible a añadirlo. Aburrido y simple gana a ingenioso.
  Menos ficheros, no más.
- Si dos soluciones ocupan lo mismo, elige la algorítmicamente correcta — pereza significa menos
  código, no menos rigor.
- Si tomas una decisión deliberada de dejar algo por debajo del óptimo (por tiempo, alcance o
  prioridad), márcalo con un comentario `# ponytail:` explicando el límite y cómo se ampliaría.
- **Nunca recortes** en: entender el problema completo antes de actuar, validación de inputs en
  fronteras de confianza, manejo de errores que evite pérdida de datos, seguridad, y todo lo que
  David haya pedido explícitamente. Toda lógica no trivial deja **una comprobación ejecutable**
  detrás (test, script o comando que la verifique).
- **Entender antes de tocar.** Lee la tarea y el código que toca, sigue el flujo real de principio a
  fin, y solo entonces sube la escalera de arriba.
- **Los bugs se arreglan en la causa raíz**, no parcheando cada llamador por separado.
- **Lee los ficheros existentes antes de escribir. No los releas si no han cambiado.** Cuidado
  especial con `dcs_meta.py` (el más grande del repo): si ya está en contexto y ni tú ni David lo
  habéis tocado desde entonces, no lo releas.
- **Salta ficheros de más de 100 KB** salvo que sean imprescindibles para la tarea.
- **No adivines APIs, versiones, flags, SHAs de commit ni nombres de paquetes.** Verifica leyendo el
  código o la documentación oficial. Si no lo has verificado, dilo explícitamente en vez de afirmarlo.
- **Paraleliza cuando sea claramente independiente:** tests vs. implementación, o features que tocan
  ficheros distintos, en la misma sesión y sin coordinación artificial de por medio. Si comparten
  ficheros clave, hazlo en serie.

---

## 3. Estilo de respuesta

Comunicación en español. Reglas de formato (aplican a toda respuesta, no solo a reportes de estado):

- **Acción primero.** Empieza por lo que hay que hacer o por la respuesta, no por el contexto o el
  preámbulo. Nada de "buena pregunta" ni resúmenes redundantes al final.
- **Tareas de varios pasos, numeradas.** Cada paso es una acción acotada, sin encadenar con "y
  luego".
- **Termina con el siguiente paso concreto** cuando quede trabajo pendiente — algo accionable, no
  una reflexión abierta.
- **No te desvíes.** Termina el problema actual antes de mencionar tangentes; los problemas
  secundarios que detectes van a `BACKLOG.md`, no a la respuesta en curso.
- **Listas de máximo 5 elementos.** Si hay más, separa en "ahora" y "después".
- **Sin emojis ni rayas largas (em-dash). Tono directo:** causa y solución, sin dramatizar
  ("uy", "por desgracia", etc.).
- Razonamiento exhaustivo en el trabajo interno; la respuesta al usuario es concisa.
- Excepciones legítimas a este formato: explicaciones conceptuales pedidas expresamente, decisiones
  destructivas (necesitan contexto completo, ver regla de la sección 4), y ambigüedad genuina donde
  hace falta preguntar antes de actuar.

---

## 4. Reglas de trabajo

1. **Documentación viva, actualizada al final de la tarea** (no en cada cambio individual):
   - `README.md` — descripción, propósito general y detalle de funcionalidades implementadas.
   - `BACKLOG.md` — features o defectos pendientes: descripción breve, justificación, dificultad.
     Cuando algo se implementa, se mueve de aquí a `CHANGELOG.md`.
   - `CHANGELOG.md` — cambios de cada versión generada.
   - `DECISIONS.md` — decisiones de proceso, lecciones aprendidas y rationale técnico de código (todo
     en un único fichero, ver su propio índice interno).
   - `ARCHITECTURE.md` — arquitectura de la aplicación.
2. **Especificación y plan previos, solo para features nuevas o cambios de arquitectura.** Para eso,
   redactamos juntos `SPEC.md` y no se avanza hasta que David lo apruebe explícitamente; luego
   presenta un plan de implementación y espera confirmación ("adelante" o equivalente) antes de
   escribir código. **Para bugfixes y ajustes puntuales de una sola sesión, ve directo**: no hace
   falta SPEC.md ni plan formal, pero si el cambio resulta ser mayor de lo esperado una vez dentro,
   párate y dilo antes de seguir.
3. **Código limpio**, siguiendo principios SOLID.
4. **TDD.** Escribe el test antes que el código. Los tests verifican **comportamiento y contratos**,
   no detalles internos de implementación: un refactor interno que no cambia el comportamiento no
   debe romper tests.
5. **Comenta el porqué, no el qué.** Evita comentarios redundantes con el propio código.
6. **Seguridad.** Valida inputs, gestiona autenticación/autorización donde aplique, no expongas
   secretos ni datos sensibles, sigue buenas prácticas básicas de seguridad.
7. **Propón mejoras.** Además de lo que David pida, anota en `BACKLOG.md` las mejoras y funcionalidades
   nuevas que veas razonables, con su justificación. **No las implementes sin aprobación previa.**
8. **Revisa `DECISIONS.md` antes de arrancar cualquier tarea nueva** para no repetir errores ya
   identificados. Si detectas que vas a repetir uno, párate y dilo. La sección de rationale técnico
   dentro de `DECISIONS.md` solo hace falta consultarla al tocar el fichero/feature concreto que cita.
9. **Nada destructivo sin aprobación explícita** de David: borrado de datos, migraciones destructivas,
   sobrescritura sin backup, `force-push`, etc. Todo cambio debe poder revertirse: commits atómicos,
   ramas, y backup antes de operaciones sensibles.
10. **Una rama por feature/bug.** Commits directos a `main` solo para documentación puramente
    descriptiva (`.md` sin efecto en comportamiento); cualquier cambio con efecto colateral real
    (código, datos que consume la UI, configuración de build o runtime) va por rama, aunque no haya
    CI que lo valide todavía.
11. **Llamadas de pago a APIs externas** (Gemini, YouTube Data API): modelo y parámetros se fijan
    explícitamente en el encargo. En tests y desarrollo van mockeadas por defecto; cualquier test que
    consuma cuota real se marca y se ejecuta solo bajo petición explícita.
12. **Toda acción de escritura real sobre servicios externos** (subir un vídeo a YouTube, publicar en
    Discord, modificar playlists) exige confirmación explícita de David para cada disparo, aunque el
    diseño del flujo ya esté aprobado.
