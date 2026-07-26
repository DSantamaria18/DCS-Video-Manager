# CHANGELOG — DCS Video Manager

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/).
Versionado semántico: `MAYOR.MENOR.PARCHE`. Cada release se etiqueta en git como `vMAYOR.MENOR.PARCHE`
(ver `DECISIONS.md`). La primera etiqueta espera a que INF-01 (CI) y SEC-01 estén resueltos.

Categorías: `Añadido`, `Cambiado`, `Obsoleto`, `Eliminado`, `Corregido`, `Seguridad`.

> **Nota de arranque.** Este fichero se crea el 2026-07-26, con el proyecto ya en marcha (78 commits).
> El histórico anterior no se versionó, así que no se reconstruyen ni versiones ni fechas: se registra un
> único punto de partida con el estado funcional verificado en `main`. A partir de aquí, cada cambio
> mergeado añade su entrada en la misma PR.

---

## [No publicado]

### Añadido

- `CLAUDE.md` — reglas de trabajo, roles del equipo de agentes y Definition of Done.
- `ARCHITECTURE.md` — arquitectura reconstruida a partir del código.
- `DECISIONS.md` — decisiones técnicas y de proceso, y lecciones aprendidas.
- `CHANGELOG.md` — este fichero.
- `SPEC.md` — plantilla de especificaciones, pendiente de rellenar con David.

### Pendiente antes de poder cortar la primera versión

- Pipeline de CI en `.github/workflows/` (hoy no existe).
- Linter y medición de cobertura declarados en `requirements-dev.txt`.
- Resolución de SEC-01 (`discord_bot_token` en fichero rastreado por git).

---

## [0.1.0] — Punto de partida

Estado funcional de `main` en el momento de crear este changelog. Verificado leyendo el código, no
inventado a partir del historial de commits.

### Añadido

**Análisis con IA**

- Extracción de N frames equiespaciados con ffmpeg (configurable 1–20, por defecto 8).
- Análisis con Gemini Vision vía REST: título, descripción, tags, capítulos, idioma, aeronave, mapa,
  tipo de misión y campaña.
- Guía de módulos (`MODULE_PROFILES`) para F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J y AH-64D,
  inyectada en el prompt para identificar la aeronave desde la cabina.
- Descripciones adaptadas a la duración: corto (<10 min), medio (10–30 min), largo (>30 min).
- Detección de series y campañas a partir del contexto, con enlaces a episodios previos.
- Historial de los últimos vídeos inyectado como contexto para mantener consistencia de estilo.
- Detección de idioma automática: español para misiones de Escuadrón 111, inglés para el resto.
- Capítulos asistidos por audio mediante `ffmpeg silencedetect`.
- Extracción de eventos tácticos de ficheros TacView `.acmi`: derribos, lanzamientos SAM, disparos BVR e
  IR, bombas guiadas, pérdidas propias y eyecciones.
- Lectura de tags y capítulos de OBS desde el contenedor MKV.
- Metadatos de respaldo cuando la llamada a Gemini falla.

**Miniaturas**

- Selección de 6 frames candidatos entre el 18% y el 78% del vídeo, puntuados por nitidez, brillo y
  colorido.
- Gradación cinematográfica y overlay estilo YouTube con título en Impact amarillo y barra inferior.
- Rejilla 2×2 en la UI para elegir candidata; descarga garantizada por debajo de 2 MB.

**YouTube**

- Autenticación OAuth2 completa (tipo *Desktop app*), con revocación desde la UI.
- Subida resumible en bloques de 10 MB con barra de progreso.
- Saneado de tags al límite de 500 caracteres, con reintento sin tags si Google los rechaza.
- Asignación a playlists con preselección automática por aeronave, tipo de misión y duración.
- Miniatura personalizada tras la subida (fallo no fatal).
- Publicación programada mediante `status.publishAt`.
- Sondeo de YouTube Analytics a 1 h, 6 h, 12 h y 24 h de la subida.
- Búsqueda de vídeos de la competencia por aeronave y tipo de misión.

**YouTube Shorts**

- Detección de clips por ventanas configurables (1–30 min) priorizando eventos ACMI y picos de audio.
- Recorte a formato vertical 9:16.
- Metadatos por clip según el tipo de evento, con editor en línea.

**Interfaz web**

- Servidor Flask local en `localhost:5000`, abre el navegador al arrancar.
- Pestañas Metadata, History, Stats y Setup.
- Selector de ficheros nativo del SO en Windows, macOS y Linux.
- Análisis asíncrono con barra de progreso por sondeo.
- Edición completa de título, descripción, tags y capítulos antes de subir.
- Vista previa de descripción con enlaces, hashtags y marcas de tiempo pulsables.
- Editor de tags en formato píldora.
- Validación SEO de la descripción con siete reglas y reescritura asistida por Gemini.
- Checklist previo a la subida.
- Detección de duplicados contra el historial.
- Informe de debrief de misión, guion de narración y captions para redes sociales.
- Dashboard de estadísticas del canal.
- Exportación del historial a CSV.
- Tema claro y oscuro con preferencia persistida.
- Edición de la configuración del canal y de las plantillas de descripción desde la UI.

**Infraestructura**

- Watcher de carpeta de grabaciones que encola automáticamente los `.mkv` nuevos.
- Notificación por webhook de Discord tras cada subida.
- Bot de Discord independiente para el Escuadrón 111 con comandos `!debrief` y `!stats` y registro de
  reacciones.
- Suite de tests con pytest.

### Seguridad

- `config/client_secret.json`, `config/youtube_token.json`, `config/last_folder.txt` y
  `memory/history.json` excluidos del repositorio.
- `GEMINI_API_KEY` leída exclusivamente de variable de entorno.
- Validación en servidor de `frames_to_extract` (1–20) y del modelo Gemini contra una allowlist.
- Todos los vídeos se suben con privacidad `private`.

### Limitaciones conocidas

Recogidas en `ARCHITECTURE.md` §7 y en `BACKLOG.md`. Las principales: `config/config.json` está
rastreado en git y admite el token del bot de Discord; no hay protección CSRF en los endpoints `POST`;
`watchdog` no está declarado en `requirements.txt`; no existe pipeline de CI.
