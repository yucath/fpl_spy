#!/usr/bin/env bash
# run_forever.sh — crash-safe scheduler launcher.
# - Restarts schedule.py if it crashes (non-zero exit).
# - Exits cleanly when schedule.py exits with code 0 (end of season).
# Start once at the beginning of the season; do not touch again.

cd "$(dirname "$0")"

PYTHON="./venv/bin/python"
SCRIPT="schedule.py"
LOG="scheduler.log"
RESTART_DELAY=60

echo "[$(date '+%Y-%m-%d %H:%M:%S')] FPL Spy run_forever started (PID $$)" | tee -a "$LOG"

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching $SCRIPT ..." | tee -a "$LOG"
    PYTHONUNBUFFERED=1 "$PYTHON" -u "$SCRIPT" 2>&1 | tee -a "$LOG"
    EXIT="${PIPESTATUS[0]}"
    if [ "$EXIT" -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Scheduler exited cleanly (season over). Done." | tee -a "$LOG"
        exit 0
    fi
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Scheduler crashed (code $EXIT). Restarting in ${RESTART_DELAY}s..." | tee -a "$LOG"
    sleep "$RESTART_DELAY"
done
