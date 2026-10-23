#!/bin/bash
# Runs INSIDE the Debian proot on the phone. Starts the notifier and the dashboard
# (bound to the whole LAN so the computer can reach it), then the engine in the
# foreground so this script — and the proot — stay alive as long as the desk runs.
#   launched by ~/sieve-start.sh on the Termux side (which holds the wake lock).
# proot Debian defaults to UTC; pin it to the user's zone (WAT/UTC+1) so timestamps,
# the daily date rollover, and hour-of-day logic match the Mac history.
export TZ="${TZ:-Africa/Lagos}"
cd "$(dirname "$0")"
./notify.sh >/dev/null 2>&1 &                                   # macOS/termux notifications (no-op if neither)
HOST=0.0.0.0 .venv/bin/python -u dashboard/server.py >> logs/dashboard.log 2>&1 &   # LAN dashboard :8787
exec ./run.sh forever                                           # engine: scans, code judge, exits. never returns.
