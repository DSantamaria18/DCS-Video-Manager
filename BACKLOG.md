# Backlog — DCS Video Manager

> Last updated: May 2026

---

> **Dependency notation:** `#N` = hard dependency (won't work without it). `#N †` = recommended order (works without it but quality or scope is reduced). OAuth scope note: `#18` and `#40` both require adding `yt-analytics.readonly` to the OAuth flow — implement together to avoid touching the auth code twice.

---

## Bugs

| # | Title | Priority | Blocks | Description |
| --- | --- | --- | --- | --- |
| 1 | Tags fail in OAuth Testing mode | 🔴 High | — | Google permanently rejects tags for unverified apps in OAuth Testing mode. The retry-without-tags fallback is in place; the message now says "Tags rejected by Google (unverified app limit) — uploaded without tags." No further fix possible until the app is verified. |
| 3 | No real-time upload progress | 🔴 High | — | Progress tracking partial — fallback warning is now shown in the UI after Gemini failures. Full chunk-by-chunk upload progress bar not yet implemented (requires _do_insert refactor with callback). |

---

## Features

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |
| 13 | Automatic YouTube Shorts generation | 🟡 Medium | #43 † | Detect action moments via audio peaks (ffmpeg) and, when TacView data (#30) is available, use its event timestamps (kills, SAM evasions, BVR engagements) as clip markers. Extract 3–5 clips of 30–60 s each with different angles/hooks ("This maneuver 🔥", "Can you spot the mistake?", "1v2 engagement"), crop to 9:16, generate per-clip Short metadata with #Shorts. Present a grid in the UI so the user can select which clips to publish before uploading. |
| 35 | Discord interactive bot for E111 | 🟢 Low | #33 | Full `discord.py` bot (beyond the simple webhook of #33): posts mission debrief (#12) to the squadron channel with interactive reaction buttons ("I'll watch", "Already watched", "Need this training"). Tracks reactions to build a dataset of which content generates most interest among squadron members. |
| 40 | Post-upload analytics tracking | 🟡 Medium | — | After a successful upload, poll the YouTube Analytics API (`yt-analytics.readonly` scope) at intervals (1h, 6h, 12h, 24h) and store views, watch time, likes, and top traffic source in `history.json` against that video. 24-hour report shown in the UI. Data feeds the optimal upload time predictor: once enough history is collected, surface "Wednesday 19:00 is your best-performing slot" based on actual channel data. Requires adding the `yt-analytics.readonly` scope to the OAuth flow — see also #18, which needs the same scope. |

---

## UX

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |

---

## Infra

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |
