---
name: run-app
description: Arrancar la UI Flask de DCS Video Manager en local, probar su API sin gastar cuota y pararla. Usar para comprobar un cambio en la app real, no solo en los tests.
---

# Arrancar la app

0. Comprueba que el puerto está libre: `netstat -ano | findstr :5000`. Si ya escucha un servidor, es de David (o una prueba anterior): no arranques otro encima, usa otro `PORT`. Dos servidores en el mismo puerto conviven en Windows y las peticiones caen en cualquiera de los dos.
1. Arranca en background: `python web/app.py` (Bash con `run_in_background`). Puerto por la variable `PORT` (5000 por defecto; en Mac, 5050 por AirPlay). `PYTHONUTF8=1` viene de `.claude/settings.json`.
2. Para no gastar cuota de Gemini ni tocar YouTube, arranca con `DCS_SIMULATE=1`: `call_gemini()` y `upload_video()` devuelven datos de ejemplo. Aun así `/api/analyze` escribe de verdad en `memory/history.json`, `memory/analysis_cache.json` y `output/`: haz copia de los dos primeros antes de probar, usa un vídeo de prueba con nombre reconocible y, al terminar, restaura las copias y borra los ficheros de `output/` que contengan "Simulated".
3. Espera a que responda `curl -s --max-time 2 http://localhost:5000/api/config`.
4. Prueba lo que toca el cambio. Sin coste: `GET /api/config`, `/api/description_templates`, `/api/history`, `/api/stats`, `/api/youtube/status`. Sin `DCS_SIMULATE`, los endpoints que llaman a Gemini (`/api/analyze`, `/api/debrief`, `/api/narration`, `/api/social_captions`, `/api/seo_rewrite`) gastan cuota: pregunta antes. Nunca llames a `/api/upload_youtube`, `/api/upload_shorts_batch` ni `/api/youtube/revoke` sin confirmación explícita de David para ese disparo.
5. Cambios de UI: abre `http://localhost:<PORT>` en el navegador y revisa la pestaña afectada.
6. Para el servidor al terminar. En Windows `python web/app.py` deja dos procesos (lanzador y python real) y `taskkill` sin `/T` mata solo uno: el otro sigue escuchando y atiende peticiones con la configuración de la prueba (p. ej. `DCS_SIMULATE=1`). Usa `taskkill /F /T /PID <pid>` con el PID de la tarea que arrancaste, no el de otro servidor.
7. Verifica que se ha ido: `netstat -ano | findstr :5000` no debe mostrar ningún LISTENING tuyo. Si queda alguno, identifica su línea de comandos y hora de inicio (`Get-CimInstance Win32_Process`) antes de matarlo, para no parar el servidor de David.
