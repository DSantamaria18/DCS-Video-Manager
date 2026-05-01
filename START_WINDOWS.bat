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
if "%ANTHROPIC_API_KEY%"=="" (
    echo.
    echo  WARNING: ANTHROPIC_API_KEY not set.
    echo  Set it with: set ANTHROPIC_API_KEY=sk-ant-...
    echo.
)

echo  Starting web server...
echo  Opening http://localhost:5000
echo.
python web\app.py
pause
