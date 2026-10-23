#!/bin/bash
# session runner: every 10 min: watch exits, scan, code judge, AI shadow judge, follow up verdicts.
# open trades get their exits checked every minute in between.
#   ./run.sh 00:00      (stop time, local, HH:MM; defaults to midnight)
#   ./run.sh forever    (never stops; prints yesterday's report just after each midnight)
#   output goes to logs/paper/session.log or logs/live/session.log, by config.PAPER
cd "$(dirname "$0")"
PY=.venv/bin/python
LOGFILE=$($PY -c "import config; print(config.SESSION_LOG)")
exec >> "$LOGFILE" 2>&1           # everything below goes to logs/<paper|live>/session.log

# portable "HH:MM today -> epoch": macOS uses `date -j`, Linux/Termux use `date -d`.
to_epoch() { date -j -f "%Y-%m-%d %H:%M" "$1" +%s 2>/dev/null || date -d "$1" +%s; }
# the AI judges call the `claude` CLI, which isn't on the phone. skip them there; the
# code judge (which makes the real buy/sell calls) always runs. run them on the computer.
command -v claude >/dev/null 2>&1 && HAVE_CLAUDE=1 || HAVE_CLAUDE=

END=${1:-00:00}
if [ "$END" = forever ]; then
  end_ts=9999999999
else
  end_ts=$(to_epoch "$(date +%Y-%m-%d) $END")
  [ "$end_ts" -le "$(date +%s)" ] && end_ts=$((end_ts + 86400))
fi
echo "$(date +%H:%M) START $($PY -c "import config; print(config.MODE)") session until $END"
day=$(date +%Y-%m-%d)
while [ "$(date +%s)" -lt "$end_ts" ]; do
  $PY watch.py 2>&1 | sed "s/^/$(date +%H:%M) WATCH /"
  $PY scan.py 2>&1 | $PY fmt.py
  $PY autojudge.py 2>&1 | sed "s/^/$(date +%H:%M) /"      # judges REVIEWs nobody judged in time
  [ -n "$HAVE_CLAUDE" ] && $PY shadowjudge.py 2>&1 | sed "s/^/$(date +%H:%M) /"   # AI verdicts, logged only, never traded (skipped on the phone)
  $PY followup.py 2>&1 | sed "s/^/$(date +%H:%M) /"       # +6h / +24h prices for every judged token
  if [ "$(date +%Y-%m-%d)" != "$day" ]; then              # new day: report the one that just ended
    $PY report.py "$day" | sed "s/^/REPORT /"
    day=$(date +%Y-%m-%d)
    if [ "$(date +%u)" = 1 ] && [ -n "$HAVE_CLAUDE" ]; then  # monday: the CEO review of last week, in the
      ($PY weeklyreview.py 7 2>&1 | sed "s/^/$(date +%H:%M) /") &   # background so exits never wait on it
    fi
  fi
  for i in 1 2 3 4 5 6 7 8 9 10; do                       # 10 min to the next scan, but open
    sleep 60                                              # trades get their exits checked every minute
    if [ "$i" -lt 10 ] && $PY -c "import book, sys; sys.exit(0 if book.load() else 1)"; then
      $PY watch.py 2>&1 | sed "s/^/$(date +%H:%M) WATCH /"
    fi
  done
done
echo "$(date +%H:%M) END"
$PY report.py "$day" | sed "s/^/REPORT /"
