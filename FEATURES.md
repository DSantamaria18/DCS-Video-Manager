# Features — DCS Video Manager

> Last updated: May 2026

Local automation tool for publishing DCS World gameplay videos to YouTube.
A local Flask web UI that combines AI-powered video analysis, metadata generation, and direct YouTube upload.

---

## AI Video Analysis

- **Frame extraction** — ffmpeg extracts N evenly-spaced frames from the video (configurable, default 8).
- **Google Gemini Vision analysis** — frames are sent to `gemini-2.5-flash` together with optional user-provided context.
- **Auto-generated metadata:**
  - YouTube-optimised title in the format `DCS World | Module | Description`
  - Long description with playlist links, social links, and a chapters section
  - Tags (up to 500 total characters)
  - Chapters with timestamps (`00:00 Briefing`, `05:30 Takeoff`, etc.)
  - Aircraft/module detected (F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache…)
  - Map detected (Caucasus, Persian Gulf, Syria, Nevada…)
  - Mission type (CAS, SEAD, Strike, BVR, Training…)
  - Video language detected (used for `defaultLanguage` and `defaultAudioLanguage` on YouTube)
- **History memory** — `history.json` stores recent analysed videos and is injected as context into the Gemini prompt to improve consistency across videos.
- **Module identification guide** — `MODULE_PROFILES` in `dcs_meta.py` provides per-aircraft cockpit identifiers, typical missions, weapons, and tag variants for all supported modules (F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache). The guide is injected verbatim into the Gemini prompt so the model can reliably identify the aircraft from cockpit frames and generate accurate descriptions and tags.
- **Squadron context** — if the user context mentions E111 or another squadron, the prompt adapts tone and format accordingly.
- **Output files** — each analysis produces a `.json` and a `.txt` file in the `output/` folder.

---

## YouTube Upload

- **OAuth2 authentication** — full Google OAuth flow (opens browser, waits for callback, saves token to `config/youtube_token.json`). Revoke button forces re-authorisation.
- **Auth status indicator** — the UI shows the current YouTube session state at all times.
- **Full upload** — sends title, description (with embedded chapters), tags, language, Gaming category (`categoryId: 20`), initial privacy `private`.
- **Playlist assignment** — loads the channel's playlists and allows assigning the video to one or more before uploading.
- **Tag-less fallback** — if the app is not Google-verified and tags fail (403 error), the upload is retried without tags and the user is notified with an amber warning.
- **Upload result** — displays the published video URL with a direct link to YouTube Studio.
- **Thumbnail upload** — if a thumbnail was generated and selected in the UI, it is automatically set on the video via `thumbnails.set` after upload. Failure is non-fatal: the video is still published and a warning is shown in the result block.
- **Reset on new video** — the upload result block is cleared automatically when a new video is selected.

---

## Thumbnail

- **Smart frame selection** — extracts 6 candidate frames between 18% and 78% of the video and scores each by sharpness (edge detection), brightness (penalises dark or washed-out frames), and colorfulness (per-channel standard deviation).
- **Cinematic colour grade** — each candidate frame receives +30% saturation, +15% contrast, and a warm push (red +5%, blue −6%).
- **YouTube-style overlay:**
  - Full frame visible — no dark gradient covering the top (where the aircraft usually is).
  - Smooth gradient in the lower area (H−320 → H−88) for text readability.
  - Title in Impact yellow with black stroke, lines placed bottom-up over the gradient.
  - Solid bottom bar with `aircraft · map` and the channel handle (`@thecylonpilot`).
- **2×2 grid in the UI** — the 4 best candidates are shown in a grid; click to select (blue outline + checkmark); the first (highest score) is auto-selected.
- **Download** — the DOWNLOAD button downloads the selected thumbnail (guaranteed < 2 MB via adaptive JPEG quality).

---

## User Interface

- **Native file picker** — opens the OS file dialog (Windows PowerShell, macOS osascript, Linux zenity) and remembers the last used folder.
- **Async analysis** — analysis runs in a background thread; the UI polls for progress and displays a progress bar with status messages.
- **All fields editable** — title (textarea, never truncated), description, tags, and chapters are all editable before uploading.
- **Description preview** — EDIT/PREVIEW toggle: preview mode renders URLs as links, `#hashtags` highlighted, and clickable timestamps in YouTube style.
- **Tag pill editor** — add tags with Enter or comma, remove with the × button on each pill or with Backspace on an empty input field.
- **Tabs** — Analyze (main workflow), History (last 20 analysed videos), Setup (channel configuration).
- **Video history** — lists the last 20 analyses with module, map, and title.
- **Dark theme** — monochromatic dark-mode UI with monospace font.

---

## Infrastructure

- **Flask web app** — local server on `http://localhost:5000`, opens the browser automatically on startup.
- **`config/config.json`** — channel name, default links (playlists, social, sponsorship, squadron), number of frames to extract, Gemini model.
- **Editable config from UI** — the Setup tab exposes a CHANNEL CONFIGURATION form that reads and writes `config.json` without touching files manually. Editable fields: channel name, channel description, squadron, frames to extract (1–20), Gemini model (dropdown), and all seven link URLs. `POST /api/config` validates `frames_to_extract` (1–20 integer) and `model` (allowlist), then merges the payload with the existing config before writing.
- **No cloud dependencies** — everything runs locally; only `GEMINI_API_KEY` and YouTube OAuth2 credentials are required.
- **Minimal dependencies** — Flask, google-api-python-client, google-auth-oauthlib, Pillow, ffmpeg (system).
- **Test suite** — 48 pytest tests covering pure functions in `dcs_meta.py` and Flask endpoints.
