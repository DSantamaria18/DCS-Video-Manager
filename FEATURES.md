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
- **Series/campaign detection** — `_detect_series()` parses the user context for episode markers ("Mission N", "Episode N", "Part N", "Ep. N", "Cap. N") to extract campaign name and episode number. Matching history entries (by campaign name in title) are surfaced as previous episodes, with `https://youtu.be/<id>` links when a `video_id` was stored after upload. `_aircraft_series_suggestions()` identifies aircraft with 3+ videos in history and surfaces them as playlist grouping candidates. Both are injected as `SERIES CONTEXT` and `AIRCRAFT PLAYLIST SUGGESTIONS` blocks in the Gemini prompt so the model can use episode numbering in titles, link previous episodes, and suggest playlist grouping. `update_memory()` now stores `campaign` (from Gemini output) and an empty `video_id` field. `update_memory_video_id(filename, video_id)` patches the most recent matching entry after a successful YouTube upload. The upload endpoint calls it automatically.
- **Audio-assisted chapter detection** — before calling Gemini, `detect_audio_chapters()` runs `ffmpeg silencedetect` (−30 dB threshold, 3 s minimum silence duration) on the video and collects `silence_end` timestamps as phase-transition candidates. Markers are filtered to a minimum 60-second gap between them, capped at 8 total, and trimmed if they fall in the last 10% of the video (likely credits/silence). When more than one marker is found, they are injected into the Gemini prompt as an `AUDIO PHASE MARKERS` block inside the CHAPTERS section, instructing the model to use the detected timestamps as preferred chapter start times and label each phase (briefing → taxi → ingress → combat → RTB). Detection is skipped for videos shorter than 10 minutes (where chapters are already suppressed). Falls back silently if ffmpeg is unavailable.
- **TacView ACMI event extraction** — `parse_acmi_events(acmi_path)` parses a `.acmi` text file (TacView 2.2 format, no external library required) and extracts kills (enemy air/ground objects with a `Destroyed` event), SAM launches (hostile weapon/missile objects with SAM-type names — SA-6, BUK, Patriot, etc.), and BVR launches (friendly AIM-120, AIM-7, AIM-54, R-77 etc.). Events are returned with timestamps in `M:SS` format. The `events_text` summary (e.g. `"1 kill(s): MiG-29 at 2:15; 1 SAM launch(es) at 5:30; 2 BVR missile(s) fired at 4:47, 8:10"`) is injected into the Gemini prompt as a `TACVIEW ACMI DATA` block, improving chapter accuracy and description specificity. The UI adds an optional ACMI file picker below the video source: selecting a file auto-parses and previews the event counts (kills, SAM launches, BVR launches). `acmi_path` is forwarded to `POST /api/analyze`; `acmi_events` is forwarded to `POST /api/debrief` to override Gemini's frame-estimated kill/SAM counts with confirmed ACMI data. New endpoint `POST /api/parse_acmi` allows previewing events independently.
- **Length-adapted descriptions** — `generate_metadata()` reads the video duration via ffprobe and classifies it into three categories: short (<10 min → "quick tactical breakdown"), medium (10–30 min → "full training video"), long (>30 min → "complete mission debrief"). `build_prompt()` receives `duration_seconds` and injects a category-specific description template and chapters rule into the Gemini prompt. Chapters are suppressed for short videos, optional for medium, and mandatory for long ones. Both English and Spanish (squadron) variants are adapted. Duration falls back to "medium" format if ffprobe fails.
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
- **Mission debrief report** — a "GENERATE DEBRIEF" button in the analysis results panel makes a second Gemini vision call (5 frames) with a debrief-focused prompt. Gemini estimates tactical stats from HUD data and RWR activity visible in the frames: mission result (RTB / CRASH / COMPLETE), enemy kills, SAM evasions, max Mach, max altitude, and fuel remaining. The report is formatted as a Discord-friendly ASCII block with a narrative paragraph written by Gemini in the video's language (Spanish for E111 squadron missions, English for solo). The block is displayed in a read-only monospace textarea with a COPY button. Exposed as `POST /api/debrief`. Gracefully falls back to metadata-only fields if the Gemini call fails.
- **Description preview** — EDIT/PREVIEW toggle: preview mode renders URLs as links, `#hashtags` highlighted, and clickable timestamps in YouTube style.
- **Description SEO optimizer** — after analysis (and on every edit with a 1-second debounce), `check_description_seo()` validates the description against seven rules: minimum 300 chars, presence of "DCS World" in title or description, aircraft name mentioned, mission type mentioned, chapter timestamps present and within the first 500 chars, and playlist link within the first 100 chars. Results appear as an inline "SEO Check" panel (warnings in amber, info in grey) between the description and tags blocks, with a RECHECK button. A FIX WITH AI button (shown when warnings exist) sends the description and issue list to Gemini via `rewrite_description_seo()` for a targeted rewrite that preserves URLs, timestamps, and hashtags. Exposed as `POST /api/seo_check` and `POST /api/seo_rewrite`.
- **Tag pill editor** — add tags with Enter or comma, remove with the × button on each pill or with Backspace on an empty input field.
- **Tabs** — Analyze (main workflow), History (last 20 analysed videos), Setup (channel configuration).
- **Video history** — lists the last 20 analyses with module, map, and title.
- **Dark theme** — monochromatic dark-mode UI with monospace font.

---

## Infrastructure

- **Flask web app** — local server on `http://localhost:5000`, opens the browser automatically on startup.
- **`config/config.json`** — channel name, default links (playlists, social, sponsorship, squadron), number of frames to extract, Gemini model.
- **Automated playlist assignment** — after analysis, `autoSelectPlaylists()` tokenises the detected `aircraft`, `mission_type`, and `campaign` fields into lowercase terms (≥2 alphanumeric chars) and pre-selects any playlist whose title contains a matching term. The selection is fully editable before upload. A green "⬡ N auto-selected" badge appears next to the playlist label when matches are found, and is cleared when a new video is chosen. The matching logic is also exposed as `POST /api/suggest_playlists` (takes `{metadata, playlists}`, returns `{suggested: [ids]}`) and as the pure Python function `_suggest_playlist_ids()` for testing.
- **Customisable description templates** — `config.json` gains a `description_templates` dict with six keys (`en_short`, `en_medium`, `en_long`, `es_short`, `es_medium`, `es_long`). `_build_description_rules()` checks for a non-empty custom override before returning the hardcoded default, so customisation is fully opt-in per template. `GET /api/description_templates` returns all six effective templates (custom or hardcoded) plus a `customised` list. `POST /api/config` merges incoming `description_templates` keys instead of replacing the whole dict, so saving one template never overwrites others. An empty string resets a template to its default. The Setup tab exposes a DESCRIPTION TEMPLATES section: a dropdown to select the template, a large textarea pre-populated with the effective content, and SAVE TEMPLATE / RESET TO DEFAULT buttons with a CUSTOM/DEFAULT badge.
- **Editable config from UI** — the Setup tab exposes a CHANNEL CONFIGURATION form that reads and writes `config.json` without touching files manually. Editable fields: channel name, channel description, squadron, frames to extract (1–20), Gemini model (dropdown), and all seven link URLs. `POST /api/config` validates `frames_to_extract` (1–20 integer) and `model` (allowlist), then merges the payload with the existing config before writing.
- **No cloud dependencies** — everything runs locally; only `GEMINI_API_KEY` and YouTube OAuth2 credentials are required.
- **Minimal dependencies** — Flask, google-api-python-client, google-auth-oauthlib, Pillow, ffmpeg (system).
- **Test suite** — 48 pytest tests covering pure functions in `dcs_meta.py` and Flask endpoints.
