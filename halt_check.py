# halt_check.py
# runs every cycle. if LIVE has lost DAILY_LOSS_HALT_USD today and no live position is still open,
# write logs/HALTED_TO_PAPER (today's date). config.py then runs everything as paper until tomorrow,
# so the scan, the judge and the follow-ups keep collecting data. live money is never touched.
# live positions that are still open keep their live exits (stops, ladder) - the flag waits until they are closed.
import csv, json, os, time
import config

day = time.strftime("%Y-%m-%d")
if not config.LIVE_REQUESTED:
    raise SystemExit
if os.path.exists(config.HALT_FLAG) and open(config.HALT_FLAG).read().strip() == day:
    raise SystemExit
trades = list(csv.DictReader(open("logs/live/trades.csv"))) if os.path.exists("logs/live/trades.csv") else []
pnl = sum(float(t["pnl"]) for t in trades if t["time"].startswith(day))
live_open = json.load(open("logs/live/positions.json")) if os.path.exists("logs/live/positions.json") else {}
if pnl <= -config.DAILY_LOSS_HALT_USD and not live_open:
    open(config.HALT_FLAG, "w").write(day)
    print(f"HALT live lost ${-pnl:.2f} today (limit ${config.DAILY_LOSS_HALT_USD}). rest of the day runs as PAPER, live resumes tomorrow")
