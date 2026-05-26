#!/usr/bin/env bash
# Remove the Gain Map JPEG Tool background service.
# Stops it first if running, then unregisters and removes the plist.

LABEL="com.ctoboilo.gainmaptool"
TARGET="gui/$(id -u)/${LABEL}"
TARGET_PLIST="${HOME}/Library/LaunchAgents/${LABEL}.plist"

if launchctl print "${TARGET}" 2>&1 | grep -q "state = running"; then
    echo "Stopping service..."
    launchctl kill SIGTERM "${TARGET}"
    sleep 1
fi

launchctl bootout "${TARGET}" 2>/dev/null || true

if [ -f "${TARGET_PLIST}" ]; then
    rm "${TARGET_PLIST}"
    echo "Removed ${TARGET_PLIST}"
fi

echo "Service uninstalled."
