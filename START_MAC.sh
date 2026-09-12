#!/bin/bash
echo ""
echo " DCS YouTube Automation - TheCylonPilot"
echo " ========================================"
echo ""

cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo " ERROR: Python not found. Install from https://python.org"
    exit 1
fi

# Create venv if it doesn't exist
if [ ! -d ".venv" ]; then
    echo " Creando entorno virtual..."
    python3 -m venv .venv
fi
source .venv/bin/activate

# Install dependencies if needed
echo " Checking dependencies..."
pip install -r requirements.txt -q

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo ""
    echo " WARNING: ANTHROPIC_API_KEY not set."
    echo " Set it with: export ANTHROPIC_API_KEY=sk-ant-..."
    echo ""
fi

echo " Starting web server..."
echo " Opening http://localhost:5000"
echo ""
python web/app.py
