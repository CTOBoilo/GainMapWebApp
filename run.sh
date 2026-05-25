#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Gain Map JPEG Tool — Start the app (macOS / Linux)
#
# Usage:
#   ./run.sh
#
# The app will open at http://127.0.0.1:5000
# (or 5001 if port 5000 is busy — common on macOS due to AirPlay).
# ─────────────────────────────────────────────────────────

set -e

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "ERROR: virtual environment not found."
    echo "Run ./setup.sh first."
    exit 1
fi

source venv/bin/activate

echo ""
echo "Starting Gain Map JPEG Tool..."
echo "Open your browser at http://127.0.0.1:5000 (or 5001)."
echo "Press Ctrl+C to stop."
echo ""

python app.py
