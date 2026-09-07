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

## Feature: Subida por lotes de YouTube Shorts

**Estado:** Aprobada 2026-09-07
**Entrada de BACKLOG.md:** FEA-06

### Problema
El botón "UPLOAD SELECTED" de la sección Shorts (`web/templates/index.html`, `uploadSelectedShorts()`)
no está implementado: solo muestra un aviso de subir manualmente en YouTube Studio. No existe backend
que suba los clips generados en `output/shorts/`.

### Objetivo
Poder seleccionar hasta 15 Shorts generados, programar su publicación escalonada (primera fecha/hora +
intervalo en días) y que la app los suba todos de una vez a YouTube, dejando que YouTube publique cada
uno en su fecha. Sin pasos manuales en YouTube Studio salvo revisar lo ya programado.

### Fuera de alcance
- Subida real distribuida en el tiempo (la app no necesita seguir corriendo días después: se sube todo
  ya, con `publishAt` escalonado — ver Riesgos y decisiones abiertas).
- Reordenar clips a mano en la UI: el orden lo fija el sufijo numérico del nombre de fichero
  (`_short_1`, `_short_2`...).
- Subida de más de 15 clips en una sola operación.
- Miniatura personalizada para Shorts (YouTube no la usa igual que en vídeo largo).

### Requisitos funcionales
- RF-1: Cada card de Short permite marcar/desmarcar un checkbox de selección; al llegar a 15
  marcados, el resto de checkboxes se deshabilita (bloqueo duro).
- RF-2: Un panel bajo "UPLOAD SELECTED" (renombrado a "PROGRAM BATCH") permite fijar fecha/hora de la
  primera publicación (`datetime-local`) y el intervalo en días (entero ≥ 1) entre publicaciones.
- RF-3: El selector de playlists ya existente se reutiliza para playlists "extra"; la playlist SHORTS
  (detectada por título, misma lógica que `_suggest_playlist_ids`) se añade siempre automáticamente,
  sin aparecer en la lista de selección para evitar duplicados.
- RF-4: El título final de cada clip subido = título del card (generado por `generate_short_metadata`
  o editado a mano) + sufijo `#N`, siendo N el índice del sufijo `_short_N` del nombre de fichero.
- RF-5: Al pulsar "PROGRAM BATCH", el frontend construye la lista ordenada por ese índice y llama una
  única vez a `POST /api/upload_shorts_batch`.
- RF-6: El backend valida el payload (clips no vacío, ≤ 15, cada `clip_path` existe, `first_publish_at`
  parseable, `interval_days` ≥ 1) devolviendo 400 si falla, antes de crear ningún job.
- RF-7: El backend crea un job y lanza un hilo que sube cada clip secuencialmente con
  `youtube_uploader.upload_video()`, calculando `publish_at = first_publish_at + interval_days*(orden-1)`.
- RF-8: Si un clip falla (excepción de `upload_video`), el job continúa con el resto; el error se
  guarda por clip y no aborta el lote.
- RF-9: `processing_status[job_id]['clips'][orden]` refleja el estado de cada clip
  (`pending`/`uploading`/`done`/`error`) para que el frontend lo pinte por card vía polling a
  `/api/status/<job_id>` (mismo mecanismo que el resto de jobs).
- RF-10: Al terminar el lote (con o sin errores parciales), el job pasa a `done` y el frontend muestra
  un toast resumen ("X/Y Shorts programados. Z fallidos.").
- RF-11: Con `DCS_SIMULATE=1`, cada clip usa la ruta simulada ya existente en `upload_video()` — sin
  llamadas reales a la API.

### Requisitos no funcionales
- Coste de API: cada clip del lote consume una unidad de cuota de subida de YouTube igual que el vídeo
  largo (hasta 15 por lote); sin llamadas nuevas a Gemini.
- Subida secuencial (no paralela) para no saturar la cuota ni complicar el manejo de progreso.
- Consistente con "ningún vídeo se publica sin revisión humana": los Shorts se suben siempre con
  `privacyStatus=private` + `publishAt` futuro (mismo comportamiento que ya fuerza `upload_video()` al
  recibir `publish_at`), nunca públicos de inmediato.

### Contratos afectados
- Nuevo endpoint `POST /api/upload_shorts_batch`. Payload:
  ```json
  {
    "clips": [
      {"clip_path": "output/shorts/x_short_1.mp4", "order": 1,
       "title": "...", "description": "...", "tags": ["..."]}
    ],
    "first_publish_at": "2026-06-01T19:00:00Z",
    "interval_days": 3,
    "playlist_ids": ["PL_extra1"]
  }
  ```
  Respuesta: `202 {"job_id": "..."}` o `400 {"error": "..."}` en validación. `401` con
  `"Not authenticated"` si no hay token OAuth (mismo patrón que `/api/upload_youtube`).
- `GET /api/status/<job_id>` ya existente amplía su forma de respuesta para este tipo de job con una
  clave `clips` (dict por orden). No cambia el contrato para jobs que no son de este tipo.
- No se modifica `youtube_uploader.upload_video()`: ya soporta `publish_at`, `playlist_ids`, `tags` y
  `DCS_SIMULATE`.

### Impacto en ficheros
- `web/app.py`: nuevo endpoint `/api/upload_shorts_batch`, función de orquestación del hilo, cálculo de
  `publish_at` por índice, extensión de `processing_status`.
- `web/templates/index.html`: panel de programación (fecha + intervalo + playlists extra), bloqueo de
  checkboxes a 15, cambio de `uploadSelectedShorts()` de stub a llamada real, badges de estado por card,
  toast resumen.
- Sin cambios en `youtube_uploader.py`, `dcs_meta.py` ni `discord_bot.py`.

### Dependencias externas
Ninguna nueva. Reutiliza YouTube Data API v3 (ya integrada) y OAuth2 ya configurado.

### Quality gates
- Cobertura de tests para el endpoint nuevo y la función de orquestación (sin umbral bloqueante, igual
  que el resto del repo — ver pregunta 3 de este documento).
- `ruff` sin errores nuevos.

### Riesgos y decisiones abiertas
- El límite de 15 clips por lote es una convención propia de David (evitar lotes descontrolados), no un
  límite documentado de la API de YouTube — se aplica como validación de la app, no como workaround de
  cuota.
- Como todos los clips se suben ya (hoy), y solo `publishAt` queda en el futuro, no hace falta ningún
  scheduler/cron que siga vivo: la app puede cerrarse tras completar el lote.

### Criterios de aceptación
- Seleccionar 15 clips habilita el bloqueo del checkbox 16.
- Programar un lote con fecha futura e intervalo de N días sube los clips con `DCS_SIMULATE=1` y cada
  uno recibe el `publish_at` correcto según su orden.
- Forzar el fallo de un clip (mock de `upload_video` lanzando excepción) no interrumpe la subida del
  resto; el resumen final refleja el fallo.
- La playlist SHORTS aparece en `playlists_added` de cada clip aunque no se seleccione ninguna playlist
  extra.
- El título subido de cada clip termina en `#N` con el N correcto.

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
