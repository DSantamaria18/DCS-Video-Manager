@echo off
echo.
echo  DCS YouTube Automation - TheCylonPilot
echo  ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install from https://python.org
    pause
    exit /b 1
)

REM Install dependencies if needed
echo  Checking dependencies...
pip install -r requirements.txt -q

REM Check API key
if "%GEMINI_API_KEY%"=="" (
    echo.
    echo  WARNING: GEMINI_API_KEY not set.
    echo  Get one at https://aistudio.google.com/app/apikey and set it with: set GEMINI_API_KEY=...
    echo.
)

set PYTHONUTF8=1
echo  Starting web server...
echo  Opening http://localhost:5000
echo.
python web\app.py
pause
