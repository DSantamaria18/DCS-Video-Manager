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

# Install dependencies if needed
echo " Checking dependencies..."
pip3 install -r requirements.txt -q

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
python3 web/app.py
