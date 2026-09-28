---
name: run-app
description: Arrancar la UI Flask de DCS Video Manager en local, probar su API sin gastar cuota y pararla. Usar para comprobar un cambio en la app real, no solo en los tests.
---

# Arrancar la app

1. Arranca en background: `python web/app.py` (Bash con `run_in_background`). Puerto por la variable `PORT` (5000 por defecto; en Mac, 5050 por AirPlay). `PYTHONUTF8=1` viene de `.claude/settings.json`.
2. Para no gastar cuota de Gemini ni tocar YouTube, arranca con `DCS_SIMULATE=1`: `call_gemini()` y `upload_video()` devuelven datos de ejemplo.
3. Espera a que responda `curl -s --max-time 2 http://localhost:5000/api/config`.
4. Prueba lo que toca el cambio. Sin coste: `GET /api/config`, `/api/description_templates`, `/api/history`, `/api/stats`, `/api/youtube/status`. Sin `DCS_SIMULATE`, los endpoints que llaman a Gemini (`/api/analyze`, `/api/debrief`, `/api/narration`, `/api/social_captions`, `/api/seo_rewrite`) gastan cuota: pregunta antes. Nunca llames a `/api/upload_youtube`, `/api/upload_shorts_batch` ni `/api/youtube/revoke` sin confirmación explícita de David para ese disparo.
5. Cambios de UI: abre `http://localhost:<PORT>` en el navegador y revisa la pestaña afectada.
6. Para el servidor al terminar (para la tarea en background, o `netstat -ano | findstr :5000` y `taskkill /F /PID <pid>`).
