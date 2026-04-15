#!/bin/bash
clear
echo ""
echo "  ╔═══════════════════════════════════════╗"
echo "  ║  ROLLON AR v32e — A&R Operating System ║"
echo "  ║  http://localhost:5001                ║"
echo "  ╚═══════════════════════════════════════╝"
echo ""

cd "$(dirname "$0")"

# Use Python 3.12 to avoid 3.14 SSL/malloc crash
PYTHON=""
for p in python3.12 python3.11 python3; do
    if command -v "$p" &>/dev/null; then
        PYTHON="$p"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ERROR: Python not found. Install Python 3.12:"
    echo "  brew install python@3.12"
    exit 1
fi

PY_VERSION=$($PYTHON --version 2>&1)
echo "  Python: $PY_VERSION"

# Warn if using 3.14
if echo "$PY_VERSION" | grep -q "3.14"; then
    echo "  ⚠ Python 3.14 detected — known SSL crash issues on macOS ARM64"
    echo "  Recommended: brew install python@3.12 && brew link python@3.12"
    echo ""
fi

# Activate venv
VENV="$HOME/tour_venv"
if [ -d "$VENV" ]; then
    source "$VENV/bin/activate"
    echo "  Venv: $VENV"
else
    echo "  No venv found at $VENV — using system Python"
fi

# Copy credentials if missing
CREDS="credentials.json"
TOKEN="token.json"
FALLBACK="$HOME/ROLLON AR"

if [ ! -f "$CREDS" ] && [ -f "$FALLBACK/$CREDS" ]; then
    echo "  Credentials missing — copying..."
    cp "$FALLBACK/$CREDS" . 2>/dev/null
    cp "$FALLBACK/$TOKEN" . 2>/dev/null
    echo "  Copied credentials from ROLLON AR folder"
fi

# Ensure gunicorn is installed for production serving
$PYTHON -c "import gunicorn" 2>/dev/null || $PYTHON -m pip install gunicorn -q

echo ""
$PYTHON app.py
