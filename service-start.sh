#!/usr/bin/env bash
# Start the Gain Map JPEG Tool as a background service.
# Survives terminal closes. Stays running until ./service-stop.sh or reboot.

LABEL="com.ctoboilo.gainmaptool"
TARGET="gui/$(id -u)/${LABEL}"

if launchctl print "${TARGET}" 2>&1 | grep -q "state = running"; then
    echo "Already running."
    echo "Open http://127.0.0.1:5001 in your browser."
    exit 0
fi

launchctl kickstart "${TARGET}"
sleep 1

if launchctl print "${TARGET}" 2>&1 | grep -q "state = running"; then
    echo "Started."
    echo "Open http://127.0.0.1:5001 in your browser."
    echo "Logs: ./logs/stdout.log and ./logs/stderr.log"
else
    echo "Failed to start. Check ./logs/stderr.log for details."
    exit 1
fi
