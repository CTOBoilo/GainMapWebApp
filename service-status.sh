#!/usr/bin/env bash
# Check whether the Gain Map JPEG Tool background service is running.

LABEL="com.ctoboilo.gainmaptool"
TARGET="gui/$(id -u)/${LABEL}"

STATE=$(launchctl print "${TARGET}" 2>&1 | grep "state = " | head -1 | awk '{print $3}')

if [ "${STATE}" = "running" ]; then
    PID=$(launchctl print "${TARGET}" 2>&1 | grep "pid = " | head -1 | awk '{print $3}')
    echo "Running (PID ${PID})"
    echo "URL: http://127.0.0.1:5001"
else
    echo "Not running"
fi
