# Backlog — DCS Video Manager

> Last updated: May 2026

---

## Bugs

| # | Title | Priority | Description |
| --- | --- | --- | --- |
| 1 | Tags fail in OAuth Testing mode | 🔴 High | Investigate whether this is a permanent Google limit for unverified apps or if there is a workaround |
| 3 | No real-time upload progress | 🔴 High | The progress bar does not advance during upload — it stays fixed until the upload finishes |

---

## Features

| # | Title | Priority | Description |
| --- | --- | --- | --- |
| 13 | Automatic YouTube Shorts generation | 🟡 Medium | Detect action moments via audio peaks (ffmpeg) and, when TacView data (#30) is available, use its event timestamps (kills, SAM evasions, BVR engagements) as clip markers. Extract 3–5 clips of 30–60 s each with different angles/hooks ("This maneuver 🔥", "Can you spot the mistake?", "1v2 engagement"), crop to 9:16, generate per-clip Short metadata with #Shorts. Present a grid in the UI so the user can select which clips to publish before uploading. |
| 16 | Schedule publish date and time | 🟡 Medium | Add a date/time picker to schedule publication instead of doing it manually from YouTube Studio. Works in combination with #17 (Batch queue): the folder watcher fills the queue, the scheduler decides when each video goes live. |
| 18 | Channel stats dashboard | 🟡 Medium | Visualise channel activity from `history.json` and YouTube Analytics API: most-recorded modules, ongoing campaigns, upload frequency, top-performing videos by views, subscriber growth. Include a monthly/fortnightly export (plain text or PDF) summarising uploads, total views, avg views per video, and recommended next content based on what performs best. Requires adding the `yt-analytics.readonly` scope to the OAuth flow. |
| 19 | Duplicate and similarity detection | 🟢 Low | Compare the current video against `history.json` and warn if a very similar mission was already uploaded. When TacView data (#30) is available, compute similarity over event profiles (same AO, same aircraft, comparable kill/evasion counts) and produce a human-readable diff ("different opponent, different map — safe to publish"). Falls back to metadata comparison (aircraft + map + mission type) when no TacView file is present. |
| 31 | OBS scene metadata context | 🟡 Medium | Read the OBS scene name and scene change timestamps from MKV file metadata and pass them to Gemini as context (e.g. `"Briefing scene: 0:00–1:30, Combat scene: 1:30–18:45"`). Requires a one-time OBS Lua/Python script setup that writes chapter markers or a `DESCRIPTION` tag to the recording at scene-change events. Implementation in the app is low-cost (ffprobe already used). |
| 32 | Social media caption generator | 🟡 Medium | Generate platform-adapted captions and hashtags from the already-analysed metadata (no re-analysis). One Gemini call produces: X/Twitter (concise, 3–5 hashtags, 280 chars, punchy tone), LinkedIn (professional/educational tone, no hashtag spam), Instagram (8–10 hashtags, social call-to-action), TikTok (15–20 hashtags, trending-youth tone). Display in the UI with one-click copy per platform. No automatic posting — direct API access is either paid (X: $100/month) or requires Meta Business approval. |
| 33 | Discord webhook notification on publish | 🟡 Medium | After a successful YouTube upload, POST to a configurable Discord webhook URL with: thumbnail, title, short description, and YouTube link. Zero extra dependencies (standard HTTP POST). Configurable in `config.json`. Companion to #35 (interactive bot). |
| 34 | Narration script generation | 🟡 Medium | Add a "Generate Script" button that sends the existing frames + metadata to Gemini with a narration-focused prompt, producing a natural-language voiceover script (`"In this mission, we launched an OCA strike over Caucasus…"`). User reviews and edits in the UI before copying. TTS integration (ElevenLabs / Azure / Google TTS) is a future bonus — not in scope here. |
| 35 | Discord interactive bot for E111 | 🟢 Low | Full `discord.py` bot (beyond the simple webhook of #33): posts mission debrief (#12) to the squadron channel with interactive reaction buttons ("I'll watch", "Already watched", "Need this training"). Tracks reactions to build a dataset of which content generates most interest among squadron members. |
| 37 | Pre-upload checklist | 🟡 Medium | Before the upload button is enabled, run a silent validation pass and show a checklist panel: title length (optimal 50–60 chars), description length (min 300 chars recommended), tags count (7–15 recommended), thumbnail filesize (<2 MB), YouTube auth status, broken links in description (HTTP HEAD), language consistency (title/description/tags all in the same language as Gemini detected). Each item shows ✓ / ⚠ / ✗ with a short fix suggestion. User can still publish with warnings. |
| 38 | Fallback metadata on Gemini failure | 🟡 Medium | When the Gemini call fails (quota exceeded, timeout, invalid API key), generate a usable fallback instead of showing an empty result: title from filename + detected aircraft, generic description template by module, default tag set by aircraft. Notify the user with an amber warning: "Analysis failed — using fallback. Edit before upload." Prevents losing a video to a transient API error. |
| 39 | Competitor video analysis | 🟡 Medium | Before publishing, search YouTube Data API for videos matching the same aircraft + mission type published in the last 7 days. Display: title, channel, publish date, total view count, tags used. Caveat: YouTube does not expose "views in first 24h" via API — only total views are available. Helps identify crowded publishing windows and borrow effective tags from similar content. |
| 40 | Post-upload analytics tracking | 🟡 Medium | After a successful upload, poll the YouTube Analytics API (`yt-analytics.readonly` scope) at intervals (1h, 6h, 12h, 24h) and store views, watch time, likes, and top traffic source in `history.json` against that video. 24-hour report shown in the UI. Data feeds the optimal upload time predictor: once enough history is collected, surface "Wednesday 19:00 is your best-performing slot" based on actual channel data. |
| 41 | Social media post preview | 🟢 Low | Before copying a caption, show a CSS mockup of how the post would appear on each platform (X card with thumbnail + text + hashtags, Instagram portrait frame, LinkedIn post layout). Pure frontend — no API calls. Helps catch formatting issues (text too long, hashtags at wrong position) before pasting manually. |

---

## UX

| # | Title | Priority | Description |
| --- | --- | --- | --- |
| 24 | History with metadata preview | 🟢 Low | Clicking a video in the history tab shows its full saved metadata from the JSON file |
| 25 | Dark/light mode toggle | 🟢 Low | The UI is always in dark mode. Add a toggle to switch to a light theme |

---

## Infra

| # | Title | Priority | Description |
| --- | --- | --- | --- |
| 17 | Batch mode with folder watcher | 🟡 Medium | Monitor the DCS Saved Games recordings folder with `watchdog` (Python). When new `.mkv` files appear, queue them automatically for analysis using the existing async job infrastructure. Display the queue in the web UI. The user reviews and approves each result before upload — no automatic publishing. Supports conditional scheduling rules configurable in `config.json`: max uploads per module per week, minimum hours between uploads, day-of-week restrictions. Works in combination with #16 (scheduled publishing). |
| 28 | Export metadata as CSV | 🟢 Low | Export the full history as CSV for analysis or external backup |
