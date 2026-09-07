# Estimación de coste antes de analizar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que los 4 botones que llaman a Gemini (ANALYZE VIDEO, GENERATE DEBRIEF, GENERATE
CAPTIONS, FIX WITH AI) muestren junto a sí cuántos frames van a mandar y con qué modelo, antes de
pulsarlos.

**Architecture:** Cambio exclusivamente frontend en `web/templates/index.html`. Un config cacheado
(`_appConfig`), obtenido con un único `fetch('/api/config')` en `DOMContentLoaded`, alimenta una
función `loadAppConfigBadges()` que pinta 4 `<span>` de badge junto a los botones. Se vuelve a
llamar tras guardar cambios en Setup (`saveConfig()`), para que los badges no queden
desactualizados. Sin cambios en `web/app.py` ni `dcs_meta.py`.

**Tech Stack:** JavaScript vanilla embebido en `web/templates/index.html` (sin build step, sin
framework de tests JS — verificación manual en navegador con `DCS_SIMULATE=1`, mismo patrón que
las tareas de frontend del plan de Shorts).

## Global Constraints

- Los 4 recuentos de frames son deterministas a partir de `_appConfig.frames_to_extract`, no
  dependen del vídeo cargado:
  - ANALYZE VIDEO → `frames_to_extract`.
  - GENERATE DEBRIEF → `min(5, frames_to_extract)`.
  - GENERATE CAPTIONS → 0 (texto).
  - FIX WITH AI (SEO) → 0 (texto).
- Formato del badge: `"{N} frame(s) · {modelo}"` si N > 0, `"Text only · {modelo}"` si N == 0.
- No se detecta el caso "vídeo ya cacheado" (fuera de alcance del spec) ni se añade contador de
  cuota diaria acumulada.
- GENERATE THUMBNAIL y GENERATE SHORTS no llevan badge (no llaman a Gemini).
- Un único `fetch('/api/config')` cacheado en `_appConfig`, reutilizado por los 4 badges — no
  repetir la llamada por botón.

---

### Task 1: Badges HTML + `loadAppConfigBadges()` + carga inicial

**Files:**
- Modify: `web/templates/index.html`

**Interfaces:**
- Produces: variable global `_appConfig` (objeto o `null`), función
  `async function loadAppConfigBadges()` que hace fetch a `/api/config`, guarda el resultado en
  `_appConfig`, y repinta los 4 `<span>` de badge (`analyzeCostBadge`, `debriefCostBadge`,
  `socialCostBadge`, `seoCostBadge`) con el texto calculado.

- [ ] **Step 1: Añadir el badge junto a ANALYZE VIDEO**

Sustituir (línea 821-823):

```html
    <button class="btn btn-primary" id="analyzeBtn" onclick="startAnalysis()">
      ⬡ &nbsp;ANALYZE VIDEO
    </button>
```

por:

```html
    <button class="btn btn-primary" id="analyzeBtn" onclick="startAnalysis()">
      ⬡ &nbsp;ANALYZE VIDEO
    </button>
    <div id="analyzeCostBadge" style="font-family:var(--mono);font-size:10px;color:var(--text3);margin-top:4px;"></div>
```

- [ ] **Step 2: Añadir el badge junto a FIX WITH AI**

Sustituir (línea 963):

```html
              <button class="copy-btn" id="seoRewriteBtn" onclick="rewriteWithAI()" style="display:none">FIX WITH AI</button>
```

por:

```html
              <button class="copy-btn" id="seoRewriteBtn" onclick="rewriteWithAI()" style="display:none">FIX WITH AI</button>
              <span id="seoCostBadge" style="font-family:var(--mono);font-size:9px;color:var(--text3);"></span>
```

- [ ] **Step 3: Añadir el badge junto a GENERATE DEBRIEF**

Sustituir (línea 1013):

```html
              <button class="action-btn" id="debriefGenBtn" onclick="generateDebrief()">GENERATE DEBRIEF</button>
```

por:

```html
              <button class="action-btn" id="debriefGenBtn" onclick="generateDebrief()">GENERATE DEBRIEF</button>
              <span id="debriefCostBadge" style="font-family:var(--mono);font-size:9px;color:var(--text3);"></span>
```

- [ ] **Step 4: Añadir el badge junto a GENERATE CAPTIONS**

Sustituir (línea 1079):

```html
            <button class="action-btn" id="socialGenBtn" onclick="generateSocialCaptions()">GENERATE CAPTIONS</button>
```

por:

```html
            <button class="action-btn" id="socialGenBtn" onclick="generateSocialCaptions()">GENERATE CAPTIONS</button>
            <span id="socialCostBadge" style="font-family:var(--mono);font-size:9px;color:var(--text3);"></span>
```

- [ ] **Step 5: Implementar `loadAppConfigBadges()`**

Añadir junto a `loadConfigForm()` (~línea 2875), antes de su definición:

```javascript
let _appConfig = null;

function _geminiCostText(nFrames) {
  const model = (_appConfig && _appConfig.model) || 'gemini-2.5-flash';
  return nFrames > 0 ? `${nFrames} frame${nFrames === 1 ? '' : 's'} · ${model}` : `Text only · ${model}`;
}

async function loadAppConfigBadges() {
  try {
    const resp = await fetch('/api/config');
    if (!resp.ok) return;
    _appConfig = await resp.json();

    const framesToExtract = _appConfig.frames_to_extract ?? 8;
    const analyzeBadge = document.getElementById('analyzeCostBadge');
    const debriefBadge = document.getElementById('debriefCostBadge');
    const socialBadge = document.getElementById('socialCostBadge');
    const seoBadge = document.getElementById('seoCostBadge');

    if (analyzeBadge) analyzeBadge.textContent = _geminiCostText(framesToExtract);
    if (debriefBadge) debriefBadge.textContent = _geminiCostText(Math.min(5, framesToExtract));
    if (socialBadge) socialBadge.textContent = _geminiCostText(0);
    if (seoBadge) seoBadge.textContent = _geminiCostText(0);
  } catch(e) {
    console.error('Could not load config for cost badges:', e);
  }
}

async function loadConfigForm() {
```

(no cambia nada más de `loadConfigForm()` — solo se inserta `loadAppConfigBadges()` justo encima
de su definición existente).

- [ ] **Step 6: Llamar a `loadAppConfigBadges()` en la carga inicial de la página**

Sustituir el bloque `DOMContentLoaded` (~línea 1456):

```javascript
document.addEventListener('DOMContentLoaded', () => {
  checkYouTubeStatus();
  loadHistory();
  loadPlaylists();
  loadConfigForm();
  loadDescriptionTemplates();
  document.getElementById('descEdit').addEventListener('input', scheduleSeoCheck);
});
```

por:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  checkYouTubeStatus();
  loadHistory();
  loadPlaylists();
  loadConfigForm();
  loadAppConfigBadges();
  loadDescriptionTemplates();
  document.getElementById('descEdit').addEventListener('input', scheduleSeoCheck);
});
```

- [ ] **Step 7: Verificación manual en navegador**

```bash
DCS_SIMULATE=1 .venv/bin/python web/app.py
```

Abrir `http://127.0.0.1:5000` (usar `127.0.0.1`, no `localhost` — en macOS `localhost:5000` puede
enrutar al receptor AirPlay del sistema en vez de a Flask). Confirmar que aparecen los 4 badges
con el `frames_to_extract`/`model` del `config/config.json` actual: "8 frames · gemini-2.5-flash"
en ANALYZE VIDEO, "5 frames · gemini-2.5-flash" en GENERATE DEBRIEF (dentro de Mission Debrief,
visible tras analizar un vídeo), "Text only · gemini-2.5-flash" en GENERATE CAPTIONS y FIX WITH AI.

- [ ] **Step 8: Commit**

```bash
git add web/templates/index.html
git commit -m "feat(cost-badges): añade badges de frames/modelo junto a los botones de Gemini"
```

---

### Task 2: Refrescar los badges tras guardar la configuración

**Files:**
- Modify: `web/templates/index.html`

**Interfaces:**
- Consumes: `loadAppConfigBadges()` (Task 1).

- [ ] **Step 1: Llamar a `loadAppConfigBadges()` tras un guardado con éxito en `saveConfig()`**

Sustituir, dentro de `saveConfig()` (~línea 2936):

```javascript
    } else {
      statusEl.style.color = 'var(--green)';
      statusEl.textContent = '✓ Saved';
      setTimeout(() => { statusEl.textContent = ''; }, 3000);
    }
```

por:

```javascript
    } else {
      statusEl.style.color = 'var(--green)';
      statusEl.textContent = '✓ Saved';
      setTimeout(() => { statusEl.textContent = ''; }, 3000);
      loadAppConfigBadges();
    }
```

- [ ] **Step 2: Verificación manual en navegador**

Con `DCS_SIMULATE=1 .venv/bin/python web/app.py` corriendo, ir a la pestaña Setup, cambiar
"Frames to extract" a un valor distinto (ej. 12) y el modelo a `gemini-2.5-pro`, pulsar guardar, y
confirmar sin recargar la página que:
- El badge de ANALYZE VIDEO pasa a "12 frames · gemini-2.5-pro".
- El badge de GENERATE DEBRIEF pasa a "5 frames · gemini-2.5-pro" (tope de 5, no 12).
- Los badges de GENERATE CAPTIONS y FIX WITH AI pasan a "Text only · gemini-2.5-pro".

Revertir el config de prueba a sus valores originales al terminar (8 / `gemini-2.5-flash`), para
no dejar cambios de config sin querer.

- [ ] **Step 3: Commit**

```bash
git add web/templates/index.html
git commit -m "feat(cost-badges): refresca los badges tras guardar cambios en Setup"
```

---

### Task 3: Documentación — cerrar FEA-03

**Files:**
- Modify: `BACKLOG.md` (eliminar la fila `FEA-03` de "Features propuestas", ya implementada)
- Modify: `CHANGELOG.md`
- Modify: `SPEC.md` (marcar la sección como Implementada)

**Interfaces:** ninguna — cambios puramente documentales.

- [ ] **Step 1: Actualizar `BACKLOG.md`**

Eliminar la fila `FEA-03` de la tabla "Features propuestas".

- [ ] **Step 2: Añadir entrada en `CHANGELOG.md`**

Bajo `[No publicado] → Añadido`, anotar: badges de frames/modelo junto a los 4 botones que llaman
a Gemini (ANALYZE VIDEO, GENERATE DEBRIEF, GENERATE CAPTIONS, FIX WITH AI), calculados a partir de
la config sin llamadas adicionales al backend (FEA-03).

- [ ] **Step 3: Marcar la sección de `SPEC.md` como implementada**

Cambiar `**Estado:** Aprobada 2026-09-07` a `**Estado:** Implementada AAAA-MM-DD` (fecha real de
cierre) en la sección "Estimación de coste antes de analizar".

- [ ] **Step 4: Commit**

```bash
git add BACKLOG.md CHANGELOG.md SPEC.md
git commit -m "docs: cierra FEA-03 (estimación de coste antes de analizar)"
```

---

## Self-Review

**Cobertura del spec:** RF-1 (identificación de los 4 botones y su coste en frames) →
implícito en `_geminiCostText`/`loadAppConfigBadges` (Task 1 Step 5), verificado con los valores
exactos por botón en Task 1 Step 7 y Task 2 Step 2. RF-2 (formato del badge) → `_geminiCostText`
(Task 1 Step 5). RF-3 (`_appConfig` cacheado, un único fetch) → Task 1 Step 5-6. RF-4 (refresco
tras guardar) → Task 2. RF-5 (Thumbnail/Shorts sin badge) → no se les añade badge en ningún step,
verificado por omisión.

**Placeholders:** ninguno pendiente.

**Consistencia de tipos:** `_geminiCostText(nFrames)` se define una vez en Task 1 Step 5 y se usa
igual (mismos 4 badges, mismos ids) en la verificación manual de Task 1 Step 7 y Task 2 Step 2. Los
ids de los `<span>` (`analyzeCostBadge`, `debriefCostBadge`, `socialCostBadge`, `seoCostBadge`)
son los mismos en el HTML (Task 1 Steps 1-4) y en `loadAppConfigBadges()` (Task 1 Step 5).