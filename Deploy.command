#!/bin/bash
# ============================================================
# ROLLON AR — One-Click Deploy
# Double-click this file to kill old processes and start fresh
# ============================================================

# Go to the rollon project folder (where this script lives)
cd "$(dirname "$0")"

# Extract version from app.py
VERSION=$(head -5 app.py | grep -oE 'v[0-9]+[a-z]*')

echo ""
echo "  ========================================="
echo "  ROLLON AR $VERSION — Starting Up"
echo "  ========================================="
echo ""

# Kill any running python3/gunicorn processes for this app
echo "  Stopping old processes..."
pkill -f "python3 app.py" 2>/dev/null
pkill -f "gunicorn.*app" 2>/dev/null
sleep 1

# Double-check they're dead
if pgrep -f "python3 app.py" >/dev/null 2>&1; then
    echo "  Force-killing stubborn processes..."
    pkill -9 -f "python3 app.py" 2>/dev/null
    sleep 1
fi

echo "  Old processes stopped."
echo ""

# Start the app
echo "  Launching ROLLON AR $VERSION on http://localhost:5001 ..."
echo ""
python3 app.py
