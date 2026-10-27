#!/bin/bash
# session runner. ONE engine, BOTH modes, every cycle:
#   the scan, the judges and the follow-ups run once and are logged as paper (the always-on data);
#   every BUY verdict then becomes a position in each mode that allows it (enter.py: own limits, own pause);
#   exits are checked for both books every 10 min, and every minute while anything is open.
#   ./run.sh 00:00      (stop time, local, HH:MM; defaults to midnight)
#   ./run.sh forever    (never stops; prints yesterday's reports just after each midnight)
# output: logs/paper/session.log gets everything. live buys, sells and reports are copied to logs/live/session.log.
cd "$(dirname "$0")"
PY=.venv/bin/python
export SIEVE_MODE=paper                # default for every step below; live steps set SIEVE_MODE=live themselves
LIVE_LOG=logs/live/session.log
mkdir -p logs/paper logs/live
exec >> logs/paper/session.log 2>&1

# portable "HH:MM today -> epoch": macOS uses `date -j`, Linux/Termux use `date -d`.
to_epoch() { date -j -f "%Y-%m-%d %H:%M" "$1" +%s 2>/dev/null || date -d "$1" +%s; }
# the AI judges call the `claude` CLI, which isn't on the phone. skip them there; the
# code judge (which makes the real buy/sell calls) always runs. run them on the computer.
command -v claude >/dev/null 2>&1 && HAVE_CLAUDE=1 || HAVE_CLAUDE=

watch_both() {                         # live first: real money gets the freshest price
  SIEVE_MODE=live $PY watch.py 2>&1 | sed "s/^/$(date +%H:%M) WATCH /" | tee -a "$LIVE_LOG"
  SIEVE_MODE=paper $PY watch.py 2>&1 | sed "s/^/$(date +%H:%M) WATCH /"
}
any_open() {
  for m in live paper; do
    [ -s "logs/$m/positions.json" ] && [ "$(tr -d ' \n' < "logs/$m/positions.json")" != "{}" ] && return 0
  done
  return 1
}
state() { [ -e "logs/$1/PAUSE_BUYS" ] && echo paused || echo on; }
reports() {
  SIEVE_MODE=paper $PY report.py "$1" | sed "s/^/REPORT paper /"
  SIEVE_MODE=live $PY report.py "$1" | sed "s/^/REPORT /" | tee -a "$LIVE_LOG"
}

END=${1:-00:00}
if [ "$END" = forever ]; then
  end_ts=9999999999
else
  end_ts=$(to_epoch "$(date +%Y-%m-%d) $END")
  [ "$end_ts" -le "$(date +%s)" ] && end_ts=$((end_ts + 86400))
fi
echo "$(date +%H:%M) START engine: paper $(state paper), live $(state live). session until $END" | tee -a "$LIVE_LOG"
day=$(date +%Y-%m-%d)
while [ "$(date +%s)" -lt "$end_ts" ]; do
  watch_both
  $PY scan.py 2>&1 | $PY fmt.py
  $PY autojudge.py 2>&1 | sed "s/^/$(date +%H:%M) /"      # judges REVIEWs nobody judged in time; fills both modes
  [ -n "$HAVE_CLAUDE" ] && $PY shadowjudge.py 2>&1 | sed "s/^/$(date +%H:%M) /"   # AI verdicts, logged only, never traded (skipped on the phone)
  $PY followup.py 2>&1 | sed "s/^/$(date +%H:%M) /"       # +6h / +24h prices for every judged token
  if [ "$(date +%Y-%m-%d)" != "$day" ]; then              # new day: report the one that just ended
    reports "$day"
    day=$(date +%Y-%m-%d)
    if [ "$(date +%u)" = 1 ] && [ -n "$HAVE_CLAUDE" ]; then  # monday: the CEO review of last week, in the
      ($PY weeklyreview.py 7 2>&1 | sed "s/^/$(date +%H:%M) /") &   # background so exits never wait on it
    fi
  fi
  for i in 1 2 3 4 5 6 7 8 9 10; do                       # 10 min to the next scan, but open
    sleep 60                                              # trades get their exits checked every minute
    if [ "$i" -lt 10 ] && any_open; then
      watch_both
    fi
  done
done
echo "$(date +%H:%M) END" | tee -a "$LIVE_LOG"
reports "$day"
