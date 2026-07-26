# DCS YouTube Automation

Personal tool for automating metadata generation and video uploads for **DCS World** content to YouTube.

Analyses video frames with **Google Gemini Vision**, automatically identifies the module, map, and mission type, and generates YouTube-optimised metadata — in English (singleplayer/campaign missions) or Spanish (Escuadrón 111 squadron missions).

---

## Features

### AI video analysis

- Extracts N evenly-spaced frames with ffmpeg (configurable, default 8)
- Analysis with `gemini-2.5-flash`: title, description, tags, chapters, language, aircraft, map, mission type, and campaign
- **Integrated module guide** — profiles for 7 modules (F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache) injected into the prompt for accurate cockpit-based identification
- **Length-adapted descriptions**: *quick breakdown* format (<10 min), *full training video* (10–30 min), or *complete mission debrief* (>30 min)
- **Series/campaign detection**: extracts campaign name and episode number from user context and injects previous episodes with links (when uploaded) so Gemini can reference them in the description
- **Last 50 videos in history** used as context to maintain style consistency across uploads
- Automatic language detection: Spanish for squadron missions, English for everything else

### Thumbnail

- Extracts 6 candidate frames between 18% and 78% of the video
- Scores each by sharpness, brightness, and colorfulness
- Cinematic colour grade: +30% saturation, +15% contrast, warm push
- YouTube-style overlay: bottom gradient, Impact yellow title with stroke, bottom info bar with `aircraft · map` and channel handle
- 2×2 grid in the UI to select the thumbnail before uploading; download guaranteed < 2 MB

### YouTube upload

- Full OAuth2 authentication (Desktop app — no redirect URI configuration needed)
- Upload with title, description, tags, language, Gaming category, and initial privacy `private`
- Custom thumbnail set automatically after upload
- Assign to one or more playlists before uploading
- **Automatic playlist pre-selection** based on detected aircraft, mission type, and campaign
- Tag-less fallback if the app is not Google-verified (403 error)

### Web UI

- Local Flask server at `http://localhost:5000`, opens automatically on startup
- **Analyze tab**: main workflow (browse → context → analysis → edit → upload)
- **History tab**: last 20 analysed videos with module, map, and title
- **Setup tab**: channel configuration (name, description, squadron, frames, Gemini model, URLs) and customisable description templates — all editable from the UI without touching files
- Async analysis with progress bar
- All fields editable before upload (title, description, tags, chapters)
- Description preview: EDIT / PREVIEW toggle with URLs as links, #hashtags highlighted, and clickable timestamps
- Tag pill editor: add with Enter or comma, remove with × or Backspace

---

## Requirements

| Tool | Minimum version | Install |
|---|---|---|
| Python | 3.10+ | [python.org](https://www.python.org/downloads/) |
| ffmpeg | any | `winget install ffmpeg` / `brew install ffmpeg` |
| Pillow | — | `pip install -r requirements.txt` |
| watchdog | 6.0+ | `pip install -r requirements-batch.txt` (opcional, solo para el batch folder watcher) |
| Gemini API key | — | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) (free, 1500 req/day) |
| YouTube OAuth2 | — | Google Cloud Console (see Setup) |

---

## Installation

```bash
git clone https://github.com/DSantamaria18/DCS-Video-Manager.git
cd DCS-Video-Manager
pip install -r requirements.txt
```

---

## Setup

### 1. Gemini API key (video analysis)

Get your free key at [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).

**Windows:**

```powershell
$env:GEMINI_API_KEY = "AIza..."
```

**Mac/Linux:**

```bash
export GEMINI_API_KEY=AIza...
```

Add this line to your `~/.zshrc` or `~/.bash_profile` to persist across sessions.

### 2. YouTube API (video upload)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a project
2. Enable **YouTube Data API v3**
3. Create OAuth2 credentials → type **Desktop app**
4. Download the file and save it as `config/client_secret.json`
5. In the **Setup** tab of the UI, click **AUTHORIZE YOUTUBE** to complete the OAuth flow

> ⚠️ `config/client_secret.json` and `config/youtube_token.json` are in `.gitignore` and are never committed to the repository.

### 3. Simulation mode (development, no quota/credentials spent)

```bash
export DCS_SIMULATE=1
```

With this flag set, `call_gemini()` and `upload_video()` return canned data instead of calling
the real APIs — useful for validating the full UI flow without Gemini quota or YouTube OAuth.

---

## Usage

### Web UI (recommended)

```bash
python web/app.py
```

Opens automatically at [http://localhost:5000](http://localhost:5000).

**Basic workflow:**

1. Click **BROWSE** and select the video
2. Enter mission context (optional but improves results)
   - Include an episode number for series detection: `"Raven One Campaign - Mission 4"`
3. Click **ANALYZE VIDEO** — Gemini analyses the frames in the background
4. Review and edit the title, description, tags, and chapters
5. Click **GENERATE THUMBNAILS** and pick the best of the 4 candidates
6. Check the auto-selected playlists and adjust if needed
7. Click **UPLOAD AS PRIVATE**

### CLI (batch processing)

```bash
# Single video
python dcs_meta.py "C:\Videos\DCS\mission.mp4" -c "A-10C II Outpost Campaign - Mission 3"

# Squadron video (detects e111/escuadron and generates in Spanish)
python dcs_meta.py "C:\Videos\DCS\op.mp4" -c "Escuadrón 111 - Operación Trueno - SEAD support"

# Full folder
python dcs_meta.py "C:\Videos\DCS\" --batch
```

---

## Advanced configuration

All settings are editable from the **Setup** tab in the UI. They can also be modified directly in `config/config.json`:

| Field | Description |
|---|---|
| `channel_name` | Channel handle (used in the thumbnail overlay) |
| `channel_description` | Channel description injected into the prompt |
| `squadron` | Squadron name |
| `frames_to_extract` | Number of frames to extract (1–20, default 8) |
| `model` | Gemini model (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-1.5-flash`, `gemini-1.5-pro`) |
| `default_links` | Playlist, social media, and sponsorship URLs |
| `description_templates` | Custom description templates by language and video length |

---

## Automatic language detection

| Context contains… | Language | Tone |
|---|---|---|
| `escuadron`, `e111`, `multiplayer`… | 🇪🇸 Spanish | Mission report style, E111 mention |
| Anything else | 🇬🇧 English | Learner style, honest, technically focused |

---

## Project structure

```text
DCS-Video-Manager/
├── dcs_meta.py              # Analysis engine (Gemini Vision + ffmpeg + thumbnail)
├── youtube_uploader.py      # YouTube upload (OAuth2 Desktop app)
├── requirements.txt
├── config/
│   ├── config.json          # Channel configuration
│   ├── client_secret.json   # ⚠️ Never commit (.gitignore)
│   └── youtube_token.json   # ⚠️ Never commit (.gitignore)
├── memory/
│   └── history.json         # Last 50 analysed videos
├── output/                  # Generated metadata (.txt + .json) + thumbnails (.jpg)
├── tests/                   # Test suite (pytest, ~150 tests)
└── web/
    ├── app.py               # Flask server + REST endpoints
    └── templates/
        └── index.html       # Web UI
```

---

## Channel

[@TheCylonPilot](https://www.youtube.com/@TheCylonPilot) — DCS World, F/A-18C Hornet, Escuadrón 111

---

## Licence

Personal use. No open source licence at this time.
