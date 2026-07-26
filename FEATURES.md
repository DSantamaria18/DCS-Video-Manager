# Features — DCS Video Manager

> Last updated: 2026-07-26 (FEA-02)

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
- **TacView ACMI event extraction** — `parse_acmi_events(acmi_path)` parses a `.acmi` text file (TacView 2.2 format) and extracts: kills (enemy air/ground destroyed), SAM launches (hostile SAM-type missiles), BVR launches (friendly AIM-120/AIM-7/AIM-54/R-77 etc.), **IR missile launches** (friendly AIM-9, R-73, etc.), **guided bomb releases** (GBU-12, GBU-31, GBU-38, Mk-82, Mk-84 etc.), **friendly aircraft losses** (shootdowns), and **ejection events** (pilot/ejected objects with Pilot/Ejected tags). All events returned with `M:SS` timestamps and injected as a `TACVIEW ACMI DATA` block in the Gemini prompt.
- **Fallback metadata on Gemini failure** — when `generate_metadata()` raises an exception (quota, timeout, bad key), the analyze endpoint catches it and calls `build_fallback_metadata()` which derives a title from the filename and user context, applies the generic English medium description template, and returns base tags. The UI shows an amber warning: "Analysis failed — using fallback metadata. Edit before upload." Upload is still possible with the fallback result.
- **Analysis cache** — `memory/analysis_cache.json` stores the last Gemini result per video, keyed by absolute path plus file size and mtime. `POST /api/analyze` checks it before extracting frames: on a hit (same file, unchanged), frame extraction and the Gemini call are both skipped and the cached metadata is reused directly, so re-analysing the same video during metadata editing costs no time and no Gemini quota. Any change to the file (re-export, re-encode) changes its mtime and invalidates the entry automatically. Fallback metadata is never cached.
- **Length-adapted descriptions** — `generate_metadata()` reads the video duration via ffprobe and classifies it into three categories: short (<10 min → "quick tactical breakdown"), medium (10–30 min → "full training video"), long (>30 min → "complete mission debrief"). `build_prompt()` receives `duration_seconds` and injects a category-specific description template and chapters rule into the Gemini prompt. Chapters are suppressed for short videos, optional for medium, and mandatory for long ones. Both English and Spanish (squadron) variants are adapted. Duration falls back to "medium" format if ffprobe fails.
- **Module identification guide** — `MODULE_PROFILES` in `dcs_meta.py` provides per-aircraft cockpit identifiers, typical missions, weapons, and tag variants for all supported modules (F/A-18C, F-16C, F-14, UH-1H, A-10C, C-130J, AH-64D Apache). The guide is injected verbatim into the Gemini prompt so the model can reliably identify the aircraft from cockpit frames and generate accurate descriptions and tags.
- **Squadron context** — if the user context mentions E111 or another squadron, the prompt adapts tone and format accordingly.
- **Output files** — each analysis produces a `.json` and a `.txt` file in the `output/` folder.

---

## YouTube Upload

- **OAuth2 authentication** — full Google OAuth flow (opens browser, waits for callback, saves token to `config/youtube_token.json`). Revoke button forces re-authorisation.
- **Auth status indicator** — the UI shows the current YouTube session state at all times.
- **Full upload** — sends title, description (with embedded chapters), tags, language, Gaming category (`categoryId: 20`), initial privacy `private`.
- **Scheduled publishing** — `upload_video()` accepts an optional `publish_at` ISO 8601 string. When set, the video is uploaded as `private` and `status.publishAt` is set so YouTube auto-publishes at the specified time.
- **Playlist assignment** — loads the channel's playlists and allows assigning the video to one or more before uploading.
- **Improved playlist matching** — `_suggest_playlist_ids()` now expands aircraft names through an alias map (F/A-18C → hornet/fa18/fa-18, F-16C → viper/f16, F-14 → tomcat, etc.) so playlists titled "Hornet Pilot" or "Viper BFM" are correctly matched.
- **Tag-less fallback** — tags rejected by Google for unverified apps are retried without tags. Message now says "Tags rejected by Google (unverified app limit) — uploaded without tags."
- **Upload result** — displays the published video URL with a direct link to YouTube Studio.
- **Thumbnail upload** — if a thumbnail was generated and selected in the UI, it is automatically set on the video via `thumbnails.set` after upload. Failure is non-fatal: the video is still published and a warning is shown in the result block.
- **Discord webhook notification** — after a successful upload, if `discord_webhook_url` is configured in `config.json`, an embed (title, URL, description excerpt) is POSTed to the Discord webhook using only `urllib.request` (no extra deps). Non-fatal: logs and continues if the webhook fails.
- **Reset on new video** — the upload result block is cleared automatically when a new video is selected.

---

## YouTube Shorts

- **Window-based clip detection** — `detect_short_clips()` divides the video into windows of configurable duration (default 5 min, UI-adjustable). For each window it picks the highest-priority ACMI event (kill → ejection → guided bomb → SAM → BVR), falls back to the loudest audio peak in that window, and finally uses the window midpoint. No hard cap on clip count — a 60-min video produces ~12 candidates.
- **Configurable window size** — the "WINDOW (MIN)" input next to the GENERATE SHORTS button controls the window length (1–30 min, default 5). Sent as `window_minutes` in `POST /api/generate_shorts`.
- **Event-context metadata** — `generate_short_metadata()` generates a distinct title and description per clip using event type and event name from ACMI: `Su-27 Kill | DCS F/A-18C #Shorts`, `AIM-120C Shot | DCS F/A-18C #Shorts`, `SA-10 Evasion | ...`, `GBU-12 Strike | ...`, `Ejection Sequence | ...`, `Cockpit Footage | ...`. Event-specific tags are appended (Kill, BVR, SAMEvasion, PrecisionStrike, etc.).
- **9:16 crop** — each clip is cropped to vertical format (`crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920`) for YouTube Shorts compatibility.
- **Card grid + copy metadata** — generated clips appear as selectable cards with COPY META and DOWNLOAD buttons per clip.
- **Inline metadata editor** — each card has an EDIT button that expands an inline panel with editable title (input), description (textarea), and tags (comma-separated input). SAVE updates the in-memory clip and refreshes the card's title display; COPY META and subsequent copies use the edited values.

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
- **Mission debrief report** — a "GENERATE DEBRIEF" button in the analysis results panel makes a second Gemini vision call (5 frames) with a debrief-focused prompt. Gemini estimates tactical stats from HUD data and RWR activity visible in the frames: mission result (RTB / CRASH / EJECT / COMPLETE), enemy kills, SAM evasions, max Mach, max altitude, and fuel remaining. EJECT is reported when Gemini detects an ejection sequence (aircraft destroyed but pilot survived). The report is formatted as a Discord-friendly ASCII block with a narrative paragraph written by Gemini in the video's language (Spanish for E111 squadron missions, English for solo). The block is displayed in a read-only monospace textarea with a COPY button. Exposed as `POST /api/debrief`. Gracefully falls back to metadata-only fields if the Gemini call fails.
- **Narration script generation** — "GENERATE SCRIPT" in the results panel calls `generate_narration_script()` via `POST /api/narration`: single Gemini call with a narration-focused prompt producing a 200-300 word first-person voiceover script. Shown in a textarea with COPY button.
- **Duplicate detection** — `check_duplicate()` compares aircraft, map, and mission_type against `history.json`. Returns `is_duplicate`, `similarity` (0.0-1.0), `matching_title`, and a human-readable `diff`. Exposed as `POST /api/check_duplicate`.
- **Pre-upload checklist** — `run_upload_checklist()` validates: title length (50-70 char warning), description ≥300 chars (fail), tag count 7-15 (warn), "DCS World" present (fail), aircraft name present (warn). Exposed as `POST /api/upload_checklist`.
- **Social media captions** — "GENERATE CAPTIONS" in the results panel calls `generate_social_captions()` via `POST /api/social_captions`: single Gemini call producing X/Twitter (≤280 chars, 3-5 hashtags), Instagram (8-10 hashtags, CTA), LinkedIn (professional, low hashtag), and TikTok (15-20 hashtags). Four-tab UI with COPY buttons per platform and collapsible CSS preview mockups for X (dark card), Instagram (gradient), and LinkedIn (white card with blue border).
- **OBS scene metadata** — `extract_obs_metadata()` reads MKV `DESCRIPTION` tag and `CHAPTER` markers via ffprobe and injects them as `OBS SCENE CONTEXT` in the Gemini prompt. Exposed as `POST /api/obs_metadata`.
- **Description preview** — EDIT/PREVIEW toggle: preview mode renders URLs as links, `#hashtags` highlighted, and clickable timestamps in YouTube style.
- **Description SEO optimizer** — after analysis (and on every edit with a 1-second debounce), `check_description_seo()` validates the description against seven rules: minimum 300 chars, presence of "DCS World" in title or description, aircraft name mentioned, mission type mentioned, chapter timestamps present and within the first 500 chars, and playlist link within the first 100 chars. Results appear as an inline "SEO Check" panel (warnings in amber, info in grey) between the description and tags blocks, with a RECHECK button. A FIX WITH AI button (shown when warnings exist) sends the description and issue list to Gemini via `rewrite_description_seo()` for a targeted rewrite that preserves URLs, timestamps, and hashtags. Exposed as `POST /api/seo_check` and `POST /api/seo_rewrite`.
- **Tag pill editor** — add tags with Enter or comma, remove with the × button on each pill or with Backspace on an empty input field.
- **Tabs** — Metadata (main workflow), History (last 20 analysed videos), Stats (channel dashboard), Setup (channel configuration).
- **Video history with preview** — clicking any row in the History tab opens a detail panel showing aircraft, map, mission type, language, title, and YouTube link (if `video_id` was stored after upload).
- **Stats dashboard** — the Stats tab calls `GET /api/stats` and renders: total upload count, bar chart of uploads by module, uploads by month, and top mission types.
- **Dark/light mode toggle** — a sun/moon button in the header switches between the dark theme (default) and a light theme via `[data-theme="light"]` CSS custom property overrides. Preference persisted to `localStorage`.
- **Competitor video analysis** — `GET /api/competitors?aircraft=&mission_type=` searches YouTube Data API for videos matching the same aircraft + mission type published in the last 7 days. Returns top 5: title, channel, publish date, video_id. Non-fatal: shows empty results if API fails.

---

## Infrastructure

- **Flask web app** — local server on `http://localhost:5000`, opens the browser automatically on startup.
- **`config/config.json`** — channel name, default links (playlists, social, sponsorship, squadron), number of frames to extract, Gemini model, `recordings_folder` (for batch watcher), `discord_webhook_url`.
- **Automated playlist assignment** — after analysis, `autoSelectPlaylists()` tokenises detected aircraft/mission_type/campaign and expands through an aircraft alias map (hornet, viper, tomcat, huey, warthog, apache, hercules) before matching against playlist titles. Exposed as `POST /api/suggest_playlists`.
- **Batch folder watcher** — `batch_watcher.py` uses `watchdog` to monitor `recordings_folder` for new `.mkv` files and queues them in `processing_status` with `status: "queued"`. Endpoints: `POST /api/batch/start`, `POST /api/batch/stop`, `GET /api/batch/status`. Users must manually approve each result before upload.
- **Export metadata as CSV** — `GET /api/export_history_csv` returns `history.json` as a downloadable CSV (date, filename, aircraft, map, mission_type, title, video_id).
- **Customisable description templates** — `config.json` gains a `description_templates` dict with six keys (`en_short`, `en_medium`, `en_long`, `es_short`, `es_medium`, `es_long`). `_build_description_rules()` checks for a non-empty custom override before returning the hardcoded default, so customisation is fully opt-in per template. `GET /api/description_templates` returns all six effective templates (custom or hardcoded) plus a `customised` list. `POST /api/config` merges incoming `description_templates` keys instead of replacing the whole dict, so saving one template never overwrites others. An empty string resets a template to its default. The Setup tab exposes a DESCRIPTION TEMPLATES section: a dropdown to select the template, a large textarea pre-populated with the effective content, and SAVE TEMPLATE / RESET TO DEFAULT buttons with a CUSTOM/DEFAULT badge.
- **Editable config from UI** — the Setup tab exposes a CHANNEL CONFIGURATION form that reads and writes `config.json` without touching files manually. Editable fields: channel name, channel description, squadron, frames to extract (1–20), Gemini model (dropdown), Discord webhook URL, and all seven link URLs. `POST /api/config` validates `frames_to_extract` (1–20 integer) and `model` (allowlist), then merges the payload with the existing config before writing.
- **No cloud dependencies** — everything runs locally; only `GEMINI_API_KEY` and YouTube OAuth2 credentials are required.
- **Minimal dependencies** — Flask, google-api-python-client, google-auth-oauthlib, Pillow, ffmpeg (system), watchdog (optional for batch watcher, `pip install -r requirements-batch.txt`).
- **Test suite** — 260 pytest tests covering pure functions in `dcs_meta.py`, Flask endpoints, and new features.
