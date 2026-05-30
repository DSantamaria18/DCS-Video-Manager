# Backlog — DCS Video Manager

> Last updated: May 2026

---

## Bugs

| # | Title | Priority | Blocks | Description |
| --- | --- | --- | --- | --- |
| 44 | Debrief result wrong when ejecting after SAM hit | 🔴 High | — | Debrief reports RTB and counts SAM evasions instead of detecting ejection. Root cause: Gemini is given 5 frames but they may all be pre-ejection; the EJECT option was added to the prompt in a previous fix but is still not being selected reliably. Additionally, ACMI-confirmed SAM hit (`friendly_losses` event) is not being used to override the Gemini result — if ACMI shows the player's aircraft was removed (hostile missile), the result must be CRASH or EJECT, never RTB. |
| 45 | Playlist auto-selection does not follow channel rules | 🔴 High | — | Playlist suggestions must follow these exact rules: (1) every DCS video → "DCS World" playlist; (2) every video → the playlist matching the aircraft flown (e.g. F/A-18C → "DCS F18"); (3) if video duration < 60 s → "SHORTS" playlist; (4) if duration > 30 min → "LARGOS" playlist. Current logic tokenises aircraft names and matches against playlist titles loosely — it misses the "DCS F18" pattern and never adds the always-required "DCS World" playlist. |
| 46 | Shorts generator produces only one clip instead of several | 🔴 High | — | `detect_short_clips()` is expected to return up to 5 clips but only one is generated. Likely causes: ACMI events are not being passed to the endpoint, candidate deduplication radius is too aggressive, or the ffmpeg crop command fails silently for most clips leaving only the first one. |
| 47 | Scheduled publish UI not visible | 🔴 High | — | The datetime picker for scheduling publication was implemented in `index.html` but does not appear in the upload section. It may be hidden, rendered outside the visible area, or its conditional display logic is broken. |

---

## Features

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |

---

## UX

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |

---

## Infra

| # | Title | Priority | Depends on | Description |
| --- | --- | --- | --- | --- |
