# Backlog — DCS Video Manager

> Última actualización: Mayo 2026

---

## Bugs

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 1 | Tags siguen fallando en modo Testing de OAuth | 🔴 Alta | Investigar si es un límite permanente de Google para apps no verificadas o si hay workaround |
| 2 | ~~El retry sin tags no notifica al usuario en la UI~~ | ✅ | Resuelto: backend devuelve `tags_skipped: true`, UI muestra aviso amber con estilo `.alert.warning`. |
| 3 | Progreso de subida en tiempo real | 🔴 Alta | La barra de progreso no muestra avance durante la subida — se queda fija hasta que termina |
| 4 | ~~No se indica el idioma del vídeo al subirlo~~ | ✅ | Resuelto: `defaultLanguage` se envía usando el idioma detectado por Gemini, pasado desde `app.py`. |
| 5 | ~~No se indica el idioma del título y descripción~~ | ✅ | Resuelto: `defaultAudioLanguage` se envía junto con `defaultLanguage`. Bug de re-detección por tags eliminado. |
| 6 | ~~Falta categoría 'Digital Combat Simulator World'~~ | ~~🔴 Alta~~ | ❌ No implementable: YouTube Data API v3 no expone un campo `gameTitle`. La asociación de juego solo se puede hacer manualmente desde YouTube Studio. `categoryId: "20"` (Gaming) es el máximo posible por API. |
| 7 | ~~El título se trunca visualmente en la UI~~ | ✅ | Resuelto: `<input>` reemplazado por `<textarea rows="2" resize:none>` — el texto hace wrap y siempre es completamente visible. |
| 30 | ~~El resultado de subida no se resetea al seleccionar un vídeo nuevo~~ | ✅ | ~~Resuelto: se limpia el bloque #uploadResult y se resetea el texto del botón al cambiar la ruta del vídeo en onPathInput() y browseFile().~~ |

---

## Features

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 8  | Descripciones adaptadas a la duración del vídeo | 🔴 Alta | Vídeos cortos (<5 min) deben tener descripción diferente a los largos — Gemini debe conocer la duración antes de generar |
| 9  | Detección de serie/campaña y numeración de episodios | 🟡 Media | Detectar en `history.json` si el vídeo pertenece a una campaña ya iniciada y sugerir número de episodio correcto |
| 10 | Capítulos automáticos por análisis de audio | 🟡 Media | ffmpeg detecta silencios y cambios de fase (briefing→despegue→combate→aterrizaje) para generar capítulos más precisos |
| 11 | Sugerencia de cortes de edición | 🟢 Baja | Detectar silencios prolongados con ffmpeg y listarlos como puntos de corte sugeridos antes de editar |
| 12 | Informe de operaciones para el E111 | 🟡 Media | Generar un resumen de misión en formato informe militar para compartir en el foro/Discord del escuadrón |
| 13 | Generación automática de YouTube Shorts | 🟡 Media | Detectar momento de acción por picos de audio (ffmpeg) + confirmar con Gemini, recortar a 9:16 y generar metadata de Short con #Shorts |
| 14 | Subir thumbnail personalizada | 🔴 Alta | Permitir seleccionar una imagen para usarla como thumbnail del vídeo al subir |
| 15 | Generación automática de thumbnail | 🟡 Media | Generar una thumbnail con el frame más representativo del vídeo + texto con título y módulo |
| 16 | Programar fecha y hora de publicación | 🟡 Media | Añadir selector de fecha/hora para programar la publicación en lugar de publicar manualmente desde YouTube Studio |
| 17 | Modo batch con UI | 🟡 Media | Permitir seleccionar múltiples vídeos y procesarlos/subirlos en cola desde la interfaz web |
| 18 | Dashboard de estadísticas del canal | 🟢 Baja | Visualizar módulos más grabados, campañas en progreso y evolución de vídeos subidos desde `history.json` |
| 19 | Detección de duplicados | 🟢 Baja | Comparar el vídeo actual contra el historial y avisar si ya se subió una grabación de la misma misión/campaña |
| 20 | Watcher de carpeta automático | 🟢 Baja | Detectar cuando DCS genera una nueva grabación en la carpeta configurada y lanzar el análisis automáticamente |
| 21 | Plantillas de descripción personalizables | 🟢 Baja | Editar las plantillas de descripción (inglés/español) desde la UI sin tocar el código |

---

## UX

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 22 | ~~Vista previa de descripción formateada~~ | ✅ | Toggle EDIT/PREVIEW en el bloque Description: renderiza links, #hashtags y timestamps con estilo YouTube. Reset automático al analizar nuevo vídeo. |
| 23 | Edición de tags en la UI | 🟡 Media | Añadir y eliminar tags individuales haciendo clic en los pills, en lugar de que sean solo de lectura |
| 24 | Historial con preview de metadata | 🟢 Baja | Al hacer clic en un vídeo del historial, mostrar su metadata completa guardada en el JSON |
| 25 | Dark/light mode toggle | 🟢 Baja | La UI siempre está en modo oscuro. Añadir toggle para cambiar a tema claro |

---

## Infra

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 26 | Soporte para módulos adicionales en el prompt | 🟡 Media | Añadir F-14, UH-1H y A-10C con sus características específicas al contexto del prompt de Gemini |
| 27 | Configuración editable desde la UI | 🟡 Media | Editar `config.json` (links, frames, modelo) desde el tab Setup sin tocar archivos manualmente |
| 28 | Exportar metadata en formato CSV | 🟢 Baja | Exportar el historial completo como CSV para análisis o backup externo |
| 29 | Soporte para OBS scene names en el contexto | 🟢 Baja | Leer el nombre de la escena de OBS desde los metadatos del archivo MKV y usarlo como contexto adicional para Gemini |
