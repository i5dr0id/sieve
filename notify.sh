#!/bin/bash
# mac notifications for the live desk: every buy, sell, error and daily report. free, no Claude.
#   (nohup ./notify.sh > /dev/null 2>&1 < /dev/null &)      stop: pkill -f notify.sh
cd "$(dirname "$0")"
LOG=logs/live/session.log         # live buys, sells and reports (run.sh copies them here)
mkdir -p logs/live && touch "$LOG"

# notify by whatever this device has: macOS osascript, or Termux's termux-notification
# (needs the Termux:API app + `pkg install termux-api`).
notify() {
  local msg="${1:0:220}"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "Sieve" sound name "Glass"' \
              -e 'end run' "$msg"
  elif command -v termux-notification >/dev/null 2>&1; then
    termux-notification --title "Sieve" --content "$msg"
  else
    :   # no notifier available; the line is still in session.log
  fi
}

tail -n 0 -F "$LOG" | grep -E --line-buffered "LIVE (BUY|sold)|WATCH|SWEEP|ERROR|Traceback|REPORT realized|WEEKLY REVIEW|END" |
while IFS= read -r line; do
  notify "$line"
done
