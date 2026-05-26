#!/usr/bin/env bash
# Stop the Gain Map JPEG Tool background service.

LABEL="com.ctoboilo.gainmaptool"
TARGET="gui/$(id -u)/${LABEL}"

if launchctl print "${TARGET}" 2>&1 | grep -q "state = running"; then
    launchctl kill SIGTERM "${TARGET}"
    sleep 1
    echo "Stopped."
else
    echo "Not running."
fi
