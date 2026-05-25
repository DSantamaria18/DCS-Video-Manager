# DCS YouTube Automation

Herramienta personal para automatizar la generación de metadata y la subida de vídeos de **DCS World** a YouTube.

Analiza los fotogramas del vídeo con **Google Gemini Vision**, identifica automáticamente el módulo, el mapa y el tipo de misión, y genera metadata optimizada para YouTube — en inglés (misiones singleplayer/campaign) o en español (misiones del Escuadrón 111).

---

## Características

### Análisis de vídeo con IA

- Extracción de N fotogramas equiespaciados con ffmpeg (configurable, 8 por defecto)
- Análisis con `gemini-2.5-flash`: título, descripción, tags, capítulos, idioma, aeronave, mapa, tipo de misión y campaña
- **Guía de módulos integrada** — perfiles de 7 módulos (F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache) inyectados en el prompt para identificación precisa desde el cockpit
- **Descripciones adaptadas a la duración**: formato *quick breakdown* (<10 min), *full training video* (10-30 min) o *complete mission debrief* (>30 min)
- **Detección de serie/campaña**: extrae nombre de campaña y número de episodio del contexto del usuario e inyecta los episodios anteriores con enlace (cuando están subidos) para que Gemini los incluya en la descripción
- **Historial de los últimos 50 vídeos** como contexto para mantener coherencia de estilo entre vídeos
- Detección de idioma: español para misiones de escuadrón, inglés para el resto

### Thumbnail

- Extracción de 6 fotogramas candidatos entre el 18 % y el 78 % del vídeo
- Puntuación por nitidez, brillo y colorido
- Grade cinematográfico: +30 % saturación, +15 % contraste, empuje cálido
- Overlay estilo YouTube: degradado inferior, título en Impact amarillo con sombra, barra inferior con `aeronave · mapa` y handle del canal
- Cuadrícula 2×2 en la UI para seleccionar el thumbnail antes de subir; descarga garantizada < 2 MB

### Subida a YouTube

- Autenticación OAuth2 completa (Desktop app — no requiere configurar redirect URI)
- Subida con título, descripción, tags, idioma, categoría Gaming y privacidad inicial `private`
- Thumbnail personalizado configurado automáticamente tras la subida
- Asignación a una o varias playlists antes de subir
- **Pre-selección automática de playlists** basada en aeronave, tipo de misión y campaña detectados
- Fallback sin tags si la app no está verificada por Google (error 403)

### Interfaz web

- Servidor Flask local en `http://localhost:5000`, se abre automáticamente
- **Pestaña Analyze**: flujo principal (browse → contexto → análisis → edición → subida)
- **Pestaña History**: últimos 20 vídeos analizados con módulo, mapa y título
- **Pestaña Setup**: configuración del canal (nombre, descripción, escuadrón, frames, modelo Gemini, URLs) y plantillas de descripción personalizables — todo editable desde la UI sin tocar ficheros
- Análisis asíncrono con barra de progreso
- Todos los campos editables antes de subir (título, descripción, tags, capítulos)
- Preview de descripción: modo EDIT / PREVIEW con URLs como enlaces, #hashtags resaltados y timestamps clicables
- Editor de tags con pills: añadir con Enter/coma, eliminar con × o Backspace

---

## Requisitos

| Herramienta | Versión mínima | Instalación |
|---|---|---|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| ffmpeg | cualquiera | `winget install ffmpeg` / `brew install ffmpeg` |
| Pillow | — | `pip install -r requirements.txt` |
| API key Gemini | — | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) (gratis, 1500 req/día) |
| OAuth2 YouTube | — | Google Cloud Console (ver Setup) |

---

## Instalación

```bash
git clone https://github.com/DSantamaria18/DCS-Video-Manager.git
cd DCS-Video-Manager
pip install -r requirements.txt
```

---

## Configuración

### 1. Gemini API Key (análisis de vídeo)

Obtén tu clave gratuita en [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

**Windows:**
```powershell
$env:GEMINI_API_KEY = "AIza..."
```

**Mac/Linux:**
```bash
export GEMINI_API_KEY=AIza...
```

Añade esta línea a tu `~/.zshrc` o `~/.bash_profile` para que persista entre sesiones.

### 2. YouTube API (subida de vídeos)

1. Ve a [console.cloud.google.com](https://console.cloud.google.com) y crea un proyecto
2. Activa **YouTube Data API v3**
3. Crea credenciales OAuth2 → tipo **Aplicación de escritorio**
4. Descarga el fichero y guárdalo como `config/client_secret.json`
5. En la pestaña **Setup** de la UI, pulsa **AUTHORIZE YOUTUBE** para completar el flujo OAuth

> ⚠️ `config/client_secret.json` y `config/youtube_token.json` están en `.gitignore` y nunca se suben al repositorio.

---

## Uso

### Interfaz web (recomendado)

```bash
python web/app.py
```

Se abre automáticamente en [http://localhost:5000](http://localhost:5000).

**Flujo básico:**
1. Pulsa **BROWSE** y selecciona el vídeo
2. Escribe el contexto de la misión (opcional pero mejora los resultados)
   - Incluye número de episodio para detección de serie: `"Raven One Campaign - Mission 4"`
3. Pulsa **ANALYZE VIDEO** — Gemini analiza los fotogramas en segundo plano
4. Revisa y edita título, descripción, tags y capítulos
5. Pulsa **GENERATE THUMBNAILS**, selecciona el mejor de los 4 candidatos
6. Comprueba las playlists pre-seleccionadas automáticamente (ajusta si hace falta)
7. Pulsa **UPLOAD AS PRIVATE**

### CLI (procesado en batch)

```bash
# Vídeo individual
python dcs_meta.py "C:\Videos\DCS\mision.mp4" -c "A-10C II Outpost Campaign - Mission 3"

# Vídeo del escuadrón (detecta e111/escuadron y genera en español)
python dcs_meta.py "C:\Videos\DCS\op.mp4" -c "Escuadrón 111 - Operación Trueno - SEAD support"

# Carpeta completa
python dcs_meta.py "C:\Videos\DCS\" --batch
```

---

## Configuración avanzada

Todos los ajustes son editables desde la pestaña **Setup** de la UI. También se pueden modificar directamente en `config/config.json`:

| Campo | Descripción |
|---|---|
| `channel_name` | Handle del canal (para el overlay del thumbnail) |
| `channel_description` | Descripción del canal inyectada en el prompt |
| `squadron` | Nombre del escuadrón |
| `frames_to_extract` | Número de fotogramas (1–20, por defecto 8) |
| `model` | Modelo Gemini (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-1.5-flash`, `gemini-1.5-pro`) |
| `default_links` | URLs de playlists, redes sociales y patrocinio |
| `description_templates` | Plantillas de descripción personalizadas por idioma y duración |

---

## Detección automática de idioma

| El contexto contiene... | Idioma | Tono |
|---|---|---|
| `escuadron`, `e111`, `multiplayer`... | 🇪🇸 Español | Informe de misión, mención al E111 |
| Cualquier otro caso | 🇬🇧 Inglés | Estilo learner, honesto, técnico |

---

## Estructura del proyecto

```text
DCS-Video-Manager/
├── dcs_meta.py              # Motor de análisis (Gemini Vision + ffmpeg + thumbnail)
├── youtube_uploader.py      # Subida a YouTube (OAuth2 Desktop app)
├── requirements.txt
├── config/
│   ├── config.json          # Configuración del canal
│   ├── client_secret.json   # ⚠️ NO subir al repo (.gitignore)
│   └── youtube_token.json   # ⚠️ NO subir al repo (.gitignore)
├── memory/
│   └── history.json         # Historial de los últimos 50 vídeos
├── output/                  # Metadata generada (.txt + .json) + thumbnails (.jpg)
├── tests/                   # Suite de tests (pytest, ~150 tests)
└── web/
    ├── app.py               # Servidor Flask + endpoints REST
    └── templates/
        └── index.html       # Interfaz web
```

---

## Canal

[@TheCylonPilot](https://www.youtube.com/@TheCylonPilot) — DCS World, F/A-18C Hornet, Escuadrón 111

---

## Licencia

Uso personal. Sin licencia open source por ahora.
