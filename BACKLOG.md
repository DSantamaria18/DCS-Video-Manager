# Backlog — DCS Video Manager

> Last updated: May 2026

---

## Bugs

| # | Title | Priority | Description |
|---|-------|----------|-------------|
| 1 | Tags fail in OAuth Testing mode | 🔴 High | Investigate whether this is a permanent Google limit for unverified apps or if there is a workaround |
| 3 | No real-time upload progress | 🔴 High | The progress bar does not advance during upload — it stays fixed until the upload finishes |

---

## Features

| # | Title | Priority | Description |
|---|-------|----------|-------------|
| 8  | Descriptions adapted to video length | 🔴 High | Short videos (<5 min) should have a different description than long ones — Gemini must know the duration before generating |
| 9  | Series/campaign detection and episode numbering | 🟡 Medium | Detect in `history.json` whether the video belongs to an ongoing campaign and suggest the correct episode number |
| 10 | Automatic chapters via audio analysis | 🟡 Medium | ffmpeg detects silences and phase changes (briefing→takeoff→combat→landing) to generate more accurate chapters |
| 11 | Edit cut suggestions | 🟢 Low | Detect prolonged silences with ffmpeg and list them as suggested cut points before editing |
| 12 | Operations report for E111 | 🟡 Medium | Generate a mission summary in military report format to share on the squadron forum/Discord |
| 13 | Automatic YouTube Shorts generation | 🟡 Medium | Detect action moments via audio peaks (ffmpeg) + confirm with Gemini, crop to 9:16, generate Short metadata with #Shorts |
| 16 | Schedule publish date and time | 🟡 Medium | Add a date/time picker to schedule publication instead of doing it manually from YouTube Studio |
| 17 | Batch mode with UI | 🟡 Medium | Allow selecting multiple videos and processing/uploading them in a queue from the web interface |
| 18 | Channel stats dashboard | 🟢 Low | Visualise most-recorded modules, ongoing campaigns, and video upload history from `history.json` |
| 19 | Duplicate detection | 🟢 Low | Compare the current video against the history and warn if a recording of the same mission/campaign was already uploaded |
| 20 | Automatic folder watcher | 🟢 Low | Detect when DCS generates a new recording in the configured folder and launch analysis automatically |
| 21 | Customisable description templates | 🟢 Low | Edit description templates (English/Spanish) from the UI without touching the code |

---

## UX

| # | Title | Priority | Description |
|---|-------|----------|-------------|
| 24 | History with metadata preview | 🟢 Low | Clicking a video in the history tab shows its full saved metadata from the JSON file |
| 25 | Dark/light mode toggle | 🟢 Low | The UI is always in dark mode. Add a toggle to switch to a light theme |

---

## Infra

| # | Title | Priority | Description |
|---|-------|----------|-------------|
| 26 | Support additional modules in prompt | 🟡 Medium | Add F-14, UH-1H, and A-10C with their specific characteristics to the Gemini prompt context |
| 27 | Editable config from UI | 🟡 Medium | Edit `config.json` (links, frames, model) from the Setup tab without touching files manually |
| 28 | Export metadata as CSV | 🟢 Low | Export the full history as CSV for analysis or external backup |
| 29 | OBS scene names in context | 🟢 Low | Read the OBS scene name from MKV file metadata and use it as additional context for Gemini |
