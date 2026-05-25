#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Gain Map JPEG Tool — Setup script (macOS / Linux)
#
# Run once, on first install:
#   ./setup.sh
#
# After that, use run.sh to start the app.
# ─────────────────────────────────────────────────────────

set -e

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo " Gain Map JPEG Tool — Setup"
echo "=========================================="
echo ""

# --- Check Python ---

if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 is not installed."
    echo ""
    echo "Install Python 3.11 or newer:"
    echo "  - macOS:  brew install python@3.12   (or download from https://www.python.org)"
    echo "  - Linux:  sudo apt install python3 python3-venv python3-pip"
    echo ""
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found Python ${PYTHON_VERSION}"

# Check version >= 3.11
PYTHON_OK=$(python3 -c 'import sys; print(1 if sys.version_info >= (3, 11) else 0)')
if [ "$PYTHON_OK" != "1" ]; then
    echo "ERROR: Python 3.11 or newer is required. You have ${PYTHON_VERSION}."
    exit 1
fi

# --- Check exiftool ---

if ! command -v exiftool &> /dev/null; then
    echo ""
    echo "WARNING: exiftool is not installed. The app will not work without it."
    echo ""
    echo "Install exiftool:"
    echo "  - macOS:  brew install exiftool"
    echo "  - Linux:  sudo apt install libimage-exiftool-perl"
    echo ""
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    EXIFTOOL_VERSION=$(exiftool -ver)
    echo "Found exiftool ${EXIFTOOL_VERSION}"
fi

# --- Create virtual environment ---

if [ -d "venv" ]; then
    echo ""
    echo "Virtual environment already exists. Skipping creation."
else
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# --- Install dependencies ---

echo ""
echo "Installing Python dependencies (this can take a minute)..."
source venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo ""
echo "=========================================="
echo " Setup complete!"
echo "=========================================="
echo ""
echo "To start the app, run:"
echo "  ./run.sh"
echo ""
