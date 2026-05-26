#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# Install the Gain Map JPEG Tool as a background launchd service.
#
# After install, use:
#   ./service-start.sh   # start in background
#   ./service-stop.sh    # stop
#   ./service-status.sh  # check
#
# To remove the service entirely, run ./service-uninstall.sh
# ─────────────────────────────────────────────────────────

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.ctoboilo.gainmaptool"
TEMPLATE="${APP_DIR}/launchd/${LABEL}.plist.template"
GENERATED="${APP_DIR}/launchd/${LABEL}.plist"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
TARGET="gui/$(id -u)/${LABEL}"

echo ""
echo "Installing Gain Map JPEG Tool background service..."
echo ""

if [ ! -f "${TEMPLATE}" ]; then
    echo "ERROR: template not found at ${TEMPLATE}"
    exit 1
fi

if [ ! -d "${APP_DIR}/venv" ]; then
    echo "ERROR: virtual environment not found. Run ./setup.sh first."
    exit 1
fi

mkdir -p "${APP_DIR}/logs"
mkdir -p "${HOME}/Library/LaunchAgents"

# Substitute __APP_DIR__ in the template with the actual project path
sed "s|__APP_DIR__|${APP_DIR}|g" "${TEMPLATE}" > "${GENERATED}"
cp "${GENERATED}" "${TARGET_PLIST}"

# Remove any previous registration silently
launchctl bootout "${TARGET}" 2>/dev/null || true

# Register the new plist with launchd
launchctl bootstrap "gui/$(id -u)" "${TARGET_PLIST}"

echo "Service installed at: ${TARGET_PLIST}"
echo ""
echo "Start the service:    ./service-start.sh"
echo "Stop the service:     ./service-stop.sh"
echo "Check status:         ./service-status.sh"
echo "Remove the service:   ./service-uninstall.sh"
echo ""
