# Features — DCS Video Manager

> Última actualización: Mayo 2026

Herramienta de automatización para publicar vídeos de DCS World en YouTube.
Interfaz web local (Flask) que combina análisis de vídeo con IA, generación de metadata y subida directa a YouTube.

---

## Análisis de vídeo con IA

- **Extracción de frames** — ffmpeg extrae N frames equiespaciados del vídeo (configurable, por defecto 8).
- **Análisis con Google Gemini Vision** — los frames se envían a `gemini-2.5-flash` junto con contexto opcional del usuario.
- **Metadata generada automáticamente:**
  - Título optimizado para YouTube con formato `DCS World | Módulo | Descripción`
  - Descripción larga con links a playlists, redes sociales y sección de capítulos
  - Tags (hasta 500 caracteres totales)
  - Capítulos con timestamps (`00:00 Briefing`, `05:30 Despegue`, etc.)
  - Módulo/aeronave detectado (F/A-18C, F-16C, A-10C, F-14, UH-1H…)
  - Mapa detectado (Caucasus, Persian Gulf, Syria, Nevada…)
  - Tipo de misión (CAS, SEAD, Strike, BVR, entrenamiento…)
  - Idioma del vídeo detectado (usado para `defaultLanguage` y `defaultAudioLanguage` en YouTube)
- **Memoria de historial** — `history.json` almacena los últimos vídeos analizados y se inyecta como contexto en el prompt de Gemini para mejorar la consistencia entre vídeos.
- **Contexto de escuadrón** — si el contexto del usuario menciona el E111 u otro escuadrón, el prompt adapta el tono y formato.
- **Ficheros de salida** — cada análisis genera un `.json` y un `.txt` en la carpeta `output/`.

---

## Subida a YouTube

- **Autenticación OAuth2** — flujo completo con Google (abre el navegador, espera el callback, guarda el token en `config/youtube_token.json`). Botón de revocar para forzar re-autorización.
- **Estado de autenticación** — indicador en la UI con el estado actual de la sesión de YouTube.
- **Upload completo** — envía al vídeo: título, descripción (con capítulos embebidos), tags, idioma, categoría Gaming (`categoryId: 20`), privacidad inicial `private`.
- **Selección de playlists** — carga las playlists del canal y permite asignar el vídeo a una o varias antes de subir.
- **Fallback sin tags** — si la app no está verificada por Google y los tags fallan (error 403), reintenta la subida sin tags y notifica al usuario con un aviso amber.
- **Resultado de subida** — muestra la URL del vídeo publicado con enlace directo a YouTube Studio.
- **Reset al cambiar vídeo** — el bloque de resultado se limpia automáticamente al seleccionar un nuevo vídeo.

---

## Thumbnail

- **Selección inteligente de frame** — extrae 6 candidatos entre el 18% y 78% del vídeo y los puntúa por nitidez (detección de bordes), brillo (penaliza frames oscuros o sobreexpuestos) y colorido (desviación estándar por canal).
- **Grade cinematográfico** — a cada frame candidato se le aplica +30% de saturación, +15% de contraste y un push cálido (rojo +5%, azul -6%).
- **Overlay estilo YouTube:**
  - Frame completo visible sin gradiente oscuro superior.
  - Gradiente suave en la zona inferior (H-320 → H-88) para legibilidad del texto.
  - Título en Impact amarillo con stroke negro, líneas posicionadas de abajo hacia arriba sobre el gradiente.
  - Barra inferior sólida con módulo · mapa y handle del canal (`@thecylonpilot`).
- **Grid 2×2 en la UI** — los 4 mejores candidatos se muestran en rejilla; click para seleccionar (borde azul + checkmark); el primero (mejor puntuación) se selecciona automáticamente.
- **Descarga** — botón DOWNLOAD descarga la thumbnail seleccionada (< 2 MB garantizado, calidad adaptativa).

---

## Interfaz de usuario

- **Selector de fichero nativo** — abre el diálogo del sistema operativo (Windows PowerShell, macOS osascript, Linux zenity) y recuerda la última carpeta usada.
- **Análisis asíncrono** — el análisis corre en un hilo separado; la UI hace polling y muestra una barra de progreso con mensajes de estado.
- **Todos los campos editables** — título (textarea, nunca truncado), descripción, tags y capítulos son editables antes de subir.
- **Preview de descripción** — toggle EDIT/PREVIEW: el modo preview renderiza URLs como links, `#hashtags` resaltados y timestamps clicables con estilo YouTube.
- **Edición de tags con pills** — añadir tags con Enter o coma, eliminar con el botón × de cada pill o con Backspace sobre el campo vacío.
- **Pestañas** — Analyze (flujo principal), History (últimos 20 vídeos analizados), Setup (configuración del canal).
- **Historial de vídeos** — lista los últimos 20 análisis con módulo, mapa y título.
- **Tema oscuro** — UI monocromática dark-mode con fuente monoespaciada.

---

## Infraestructura

- **Flask web app** — servidor local en `http://localhost:5000`, abre el navegador automáticamente al arrancar.
- **Configuración en `config/config.json`** — nombre del canal, links por defecto (playlists, redes, patrocinio, escuadrón), número de frames a extraer, modelo de Gemini.
- **Sin dependencias de cloud** — todo corre en local; solo se requiere `GEMINI_API_KEY` y credenciales OAuth2 de YouTube.
- **Dependencias mínimas** — Flask, google-api-python-client, google-auth-oauthlib, Pillow, ffmpeg (sistema).
- **Suite de tests** — 48 tests con pytest cubren funciones puras de `dcs_meta.py` y endpoints de Flask.
