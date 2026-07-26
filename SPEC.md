# SPEC.md — DCS Video Manager

Documento de especificaciones. **La regla 2 de `CLAUDE.md` exige que se redacte conjuntamente con David
y que él lo apruebe explícitamente antes de escribir código.** Por eso este fichero es una plantilla con
las secciones a rellenar, no un documento ya escrito por un agente.

**Estado: BORRADOR — sin aprobar.**

---

## Cómo se usa

- Se abre una sección `## Feature: <nombre>` por cada desarrollo nuevo.
- El Tech Lead la redacta con David, incluyendo preguntas abiertas.
- Nadie escribe código hasta que David apruebe explícitamente esa sección.
- Aprobada la especificación, el Tech Lead la divide en tareas y presenta el plan detallado (regla 3).
  El plan también necesita luz verde explícita antes de tocar código.
- Cuando la feature se implementa, la sección se conserva aquí como referencia histórica y el resultado
  se registra en `CHANGELOG.md` y `FEATURES.md`.

---

## Plantilla por feature

```markdown
## Feature: <nombre>

**Estado:** Borrador | Aprobada AAAA-MM-DD | Implementada AAAA-MM-DD | Descartada
**Entrada de BACKLOG.md:** <id>

### Problema
Qué duele hoy y a quién. Sin solución todavía.

### Objetivo
Qué debe ser cierto cuando esto esté hecho.

### Fuera de alcance
Qué NO se hace en esta iteración, para evitar que crezca sola.

### Requisitos funcionales
Numerados y verificables (RF-1, RF-2...). Cada uno debe poder convertirse en un test.

### Requisitos no funcionales
Rendimiento, coste de API, comportamiento sin conexión, límites de cuota, compatibilidad de SO.
Los define QA junto al Tech Lead.

### Contratos afectados
Endpoints nuevos o modificados, forma del payload de entrada y de salida, cambios en el esquema de
config.json o de history.json. Marca explícitamente si algo cruza la frontera servidor ↔ navegador:
eso obliga a verificación en navegador real.

### Impacto en ficheros
Qué módulos se tocan. Sirve para decidir si la feature es separable entre los 2 Developers o debe ir
a uno solo.

### Dependencias externas
Paquetes nuevos (verificados contra documentación oficial), credenciales necesarias, cuotas de API.
Las credenciales se piden ANTES de despachar a QA.

### Quality gates
Cobertura mínima, linting, tests de seguridad aplicables. Los define QA.

### Riesgos y decisiones abiertas
Qué puede salir mal y qué preguntas quedan para David.

### Criterios de aceptación
Lista comprobable. Es lo que QA valida antes de que el Tech Lead haga el review.
```

---

## Contexto permanente del producto

Esto no se renegocia por feature; es el marco en el que encaja todo lo demás. Verificado contra el código
actual.

- **Usuario único:** David. Aplicación local, sin multiusuario ni despliegue en nube.
- **Objetivo del producto:** reducir a minutos el trabajo manual de preparar y publicar un vídeo de DCS
  World en el canal @TheCylonPilot.
- **Ningún vídeo se publica sin revisión humana.** La subida es siempre `private`; la publicación es una
  decisión aparte.
- **Idiomas de salida:** inglés por defecto; español para misiones del Escuadrón 111.
- **Coste:** Gemini y la YouTube Data API tienen cuota. Cualquier feature que multiplique las llamadas
  necesita justificación explícita del coste.
- **Sin build step en frontend.** La UI es un único HTML con su JS embebido, servido por Flask.

---

## Preguntas abiertas para David

Pendientes de respuesta. El Tech Lead las traslada; ningún otro agente pregunta directamente.

1. **Prioridad de SEC-01.** `config/config.json` está rastreado en git y la pestaña Setup escribe ahí
   `discord_bot_token`. Hoy está vacío, pero en cuanto lo rellenes y hagas commit, el token queda público.
   ¿Se arregla antes que cualquier otra cosa?
2. **Alcance del CI.** No existe `.github/workflows/`. La Definition of Done exige CI real en verde, así
   que hoy es incumplible. ¿Qué debe correr el CI en la primera versión: solo pytest, o también linter y
   umbral de cobertura?
   **Respuesta (2026-07-26):** pytest + linter (`ruff`) + coverage (`pytest-cov`), los tres bloqueantes
   desde el primer CI. Coverage se mide y reporta pero sin umbral mínimo (ver pregunta 3). Pendiente de
   ejecutar: INF-01 (crear `.github/workflows/`).
3. **Umbral de cobertura.** ¿Qué porcentaje mínimo aceptas como quality gate, sabiendo que `dcs_meta.py`
   concentra la mayor parte de la lógica?
   **Respuesta (2026-07-26):** sin umbral bloqueante por ahora. Se mide y reporta (`--cov-report=term-missing`
   en `pytest.ini`), no falla el build por debajo de un %.
4. **Refactor de `dcs_meta.py`.** Son ~2.200 líneas mezclando dominio, I/O, subprocesos y HTTP. Partirlo
   mejora el cumplimiento de la regla 4 (SOLID) pero es una PR grande y arriesgada. ¿Se aborda ahora, se
   hace de forma incremental, o se congela?
   **Respuesta (2026-07-26):** incremental, una PR por dominio (TEC-01a–e en `BACKLOG.md`), en orden de
   menor a mayor acoplamiento: `acmi/` → `thumbnail/` → `media/` → `gemini/` → `seo/`. `dcs_meta.py`
   reexporta cada símbolo movido, así ninguna PR toca los 47 call sites en `web/app.py`,
   `discord_bot.py`, `batch_watcher.py` y `youtube_uploader.py`.
5. **Tests que consumen cuota real.** ¿Autorizas una suite marcada de tests de integración contra Gemini
   y YouTube que se ejecute solo bajo petición, o todo debe ir mockeado siempre?
6. **Versionado.** ¿Empezamos a etiquetar releases con tags de git a partir de la próxima entrega, o el
   `CHANGELOG.md` basta?
   **Respuesta (2026-07-26):** tags de git, a partir de la próxima entrega. Ver `DECISIONS.md`. La
   primera etiqueta espera a que INF-01 (CI) y SEC-01 estén resueltos (ver `CHANGELOG.md`).
7. **`README.md` desactualizado.** No documenta Shorts, ACMI, debrief, narración, captions, Stats, watcher
   de lotes ni el bot de Discord. ¿Lo actualizamos como tarea propia o se va arreglando por partes?
