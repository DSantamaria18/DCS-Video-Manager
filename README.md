# DCS YouTube Automation

Herramienta personal para automatizar la generación de metadata (título, descripción, tags, capítulos) y subida de vídeos de **DCS World** a YouTube.

Analiza los fotogramas del vídeo usando **Google Gemini Vision** e identifica automáticamente el módulo, el mapa y el tipo de misión. Genera metadata optimizada para YouTube en inglés (misiones singleplayer) o español (misiones del Escuadrón 111).

---

## Características

- 🎬 Analiza vídeos MKV y MP4 extrayendo fotogramas con ffmpeg
- 🤖 Genera título, descripción, tags y capítulos con Gemini Vision
- 🌐 Interfaz web local con estética de aviónica militar
- 📤 Subida directa a YouTube como **privado** (publicas tú manualmente)
- 📋 Selección múltiple de playlists
- 🇪🇸 Detección automática de idioma: inglés para singleplayer, español para misiones del E111
- 💾 Historial de los últimos 50 vídeos procesados para mantener consistencia de estilo

---

## Requisitos

| Herramienta | Versión mínima | Instalación |
|---|---|---|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| ffmpeg | cualquiera | `winget install ffmpeg` / `brew install ffmpeg` |
| API key Gemini | — | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) (gratis, 1500 req/día) |
| OAuth2 YouTube | — | Google Cloud Console (ver Setup) |

---

## Instalación

```bash
git clone https://github.com/TU_USUARIO/dcs-youtube-automation.git
cd dcs-youtube-automation
pip install -r requirements.txt
```

---

## Configuración

### 1. Gemini API Key (análisis de vídeo)

Obtén tu clave gratuita en [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

**Windows:**
```powershell
set GEMINI_API_KEY=AIza...
```

**Mac/Linux:**
```bash
export GEMINI_API_KEY=AIza...
```
Añade esta línea a tu `~/.zshrc` o `~/.bash_profile` para que persista.

### 2. YouTube API (subida de vídeos)

1. Ve a [console.cloud.google.com](https://console.cloud.google.com) y crea un proyecto
2. Activa **YouTube Data API v3**
3. Crea credenciales OAuth2 → tipo **Aplicación de escritorio**
4. Descarga el fichero y guárdalo como `config/client_secret.json`

> ⚠️ `config/client_secret.json` y `config/youtube_token.json` están en `.gitignore` y nunca se suben al repositorio.

---

## Uso

### Interfaz web (recomendado)

```bash
python web/app.py
```

Se abre automáticamente en [http://localhost:5000](http://localhost:5000).

**Flujo:**
1. Pulsa **BROWSE** y selecciona el vídeo
2. Escribe el contexto de la misión (opcional pero mejora los resultados)
3. Pulsa **ANALYZE VIDEO** — Gemini analiza los fotogramas
4. Revisa y edita el título y la descripción generados
5. Selecciona las playlists y pulsa **UPLOAD AS PRIVATE**

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

## Estructura del proyecto

```
dcs-youtube-automation/
├── dcs_meta.py              # Motor de análisis (Gemini Vision + ffmpeg)
├── youtube_uploader.py      # Subida a YouTube (OAuth2 Desktop app)
├── requirements.txt
├── START_WINDOWS.bat        # Lanzador para Windows
├── config/
│   ├── config.json          # Configuración del canal
│   ├── client_secret.json   # ⚠️ NO subir al repo (.gitignore)
│   └── youtube_token.json   # ⚠️ NO subir al repo (.gitignore)
├── memory/
│   └── history.json         # Historial de vídeos procesados
├── output/                  # Metadata generada (.txt + .json)
└── web/
    ├── app.py               # Servidor Flask
    └── templates/
        └── index.html       # Interfaz web
```

---

## Detección automática de idioma

| El contexto contiene... | Idioma | Tono |
|---|---|---|
| `escuadron`, `e111`, `multiplayer`... | 🇪🇸 Español | Informe de misión, mención al E111 |
| Cualquier otro caso | 🇬🇧 Inglés | Estilo learner, honesto, técnico |

---

## Canal

[@TheCylonPilot](https://www.youtube.com/@TheCylonPilot) — DCS World, F/A-18C Hornet, Escuadrón 111

---

## Licencia

Uso personal. Sin licencia open source por ahora.
