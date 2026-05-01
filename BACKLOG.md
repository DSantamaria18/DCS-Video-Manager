# Backlog — DCS Video Manager

> Última actualización: Mayo 2026

---

## Bugs

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 1 | Tags siguen fallando en modo Testing de OAuth | 🔴 Alta | Investigar si es un límite permanente de Google para apps no verificadas o si hay workaround |
| 2 | El retry sin tags no notifica al usuario en la UI | 🔴 Alta | Cuando se hace retry sin tags, la UI no avisa. El usuario no sabe que subió sin tags |
| 3 | Progreso de subida en tiempo real | 🔴 Alta | La barra de progreso no muestra avance durante la subida — se queda fija hasta que termina |
| 4 | No se indica el idioma del vídeo al subirlo | 🔴 Alta | El campo `defaultLanguage` no se envía a YouTube — debe ser `es` o `en` según el tipo de vídeo |
| 5 | No se indica el idioma del título y descripción | 🔴 Alta | `defaultAudioLanguage` tampoco se envía. YouTube no puede indexar correctamente el vídeo por idioma |
| 6 | Falta categoría 'Digital Combat Simulator World' | 🔴 Alta | El campo game/title no se envía en los metadatos. YouTube no asocia el vídeo al juego en su base de datos |
| 7 | El título se trunca visualmente en la UI | 🟡 Media | El campo título muestra `...` cuando supera el ancho del input |

---

## Features

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 8 | Descripciones adaptadas a la duración del vídeo | 🔴 Alta | Vídeos cortos (<5 min) deben tener descripción diferente a los largos — Gemini debe conocer la duración antes de generar |
| 9 | Generación automática de YouTube Shorts | 🟡 Media | Detectar momento de acción por picos de audio (ffmpeg) + confirmar con Gemini, recortar a 9:16 y generar metadata de Short con #Shorts |
| 10 | Subir thumbnail personalizada | 🔴 Alta | Permitir seleccionar una imagen para usarla como thumbnail del vídeo al subir |
| 11 | Generación automática de thumbnail | 🟡 Media | Generar una thumbnail con el frame más representativo del vídeo + texto con título y módulo |
| 12 | Programar fecha y hora de publicación | 🟡 Media | Añadir selector de fecha/hora para programar la publicación en lugar de publicar manualmente desde YouTube Studio |
| 13 | Modo batch con UI | 🟡 Media | Permitir seleccionar múltiples vídeos y procesarlos/subirlos en cola desde la interfaz web |
| 14 | Watcher de carpeta automático | 🟢 Baja | Detectar cuando DCS genera una nueva grabación en la carpeta configurada y lanzar el análisis automáticamente |
| 15 | Plantillas de descripción personalizables | 🟢 Baja | Editar las plantillas de descripción (inglés/español) desde la UI sin tocar el código |

---

## UX

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 16 | Vista previa de descripción formateada | 🟡 Media | Mostrar la descripción con el formato real de YouTube (emojis, saltos de línea) en lugar de texto plano en el textarea |
| 17 | Edición de tags en la UI | 🟡 Media | Añadir y eliminar tags individuales haciendo clic en los pills, en lugar de que sean solo de lectura |
| 18 | Historial con preview de metadata | 🟢 Baja | Al hacer clic en un vídeo del historial, mostrar su metadata completa guardada en el JSON |
| 19 | Dark/light mode toggle | 🟢 Baja | La UI siempre está en modo oscuro. Añadir toggle para cambiar a tema claro |

---

## Infra

| # | Título | Prioridad | Descripción |
|---|--------|-----------|-------------|
| 20 | Soporte para módulos adicionales en el prompt | 🟡 Media | Añadir F-14, UH-1H y A-10C con sus características específicas al contexto del prompt de Gemini |
| 21 | Configuración editable desde la UI | 🟡 Media | Editar `config.json` (links, frames, modelo) desde el tab Setup sin tocar archivos manualmente |
| 22 | Exportar metadata en formato CSV | 🟢 Baja | Exportar el historial completo como CSV para análisis o backup externo |
| 23 | Soporte para OBS scene names en el contexto | 🟢 Baja | Leer el nombre de la escena de OBS desde los metadatos del archivo MKV y usarlo como contexto adicional para Gemini |
