# report.py
# the evening report. everything in it comes from checks.csv and trades.csv, nothing from memory.
import csv, os, sys, time
from collections import Counter
from config import DECISIONS as LOG, PAPER
import book

day = sys.argv[1] if len(sys.argv) > 1 else time.strftime("%Y-%m-%d")   # python report.py 2026-10-18
checks = [r for r in csv.DictReader(open(LOG))] if os.path.exists(LOG) else []
checks = [r for r in checks if r["time"].startswith(day)]
done = [t for t in book.trades() if t["time"].startswith(day) and t["action"] != "open"]

by_stage = Counter(r["stage"] for r in checks if r["verdict"] == "SKIP")
buys = [r for r in checks if r["verdict"] == "BUY"]
wins = [t for t in done if float(t["pnl"]) > 0]
reasons = Counter(r["reason"] for r in checks if r["stage"] in ("facts", "pool"))

print(f"EVENING REPORT {day} {'(PAPER)' if PAPER else '(LIVE)'}")
print(f"checked: {len(checks)}")
print(f"killed by rug filter: {by_stage['facts']} | by pool: {by_stage['pool']} | "
      f"by judge: {by_stage['grok'] + by_stage['claude'] + by_stage['code']} | by limits: {by_stage['limits']}")
print(f"sent to review: {sum(1 for r in checks if r['verdict'] == 'REVIEW')}")
print(f"bought: {len(buys)} | open now: {len(book.load())}")
print(f"realized pnl: ${book.today_pnl(day):+.2f}")
if done:
    print(f"green exits: {len(wins)}/{len(done)}")
    best = max(done, key=lambda t: float(t["pnl"]))
    worst = min(done, key=lambda t: float(t["pnl"]))
    print(f"best: {best['symbol']} ${float(best['pnl']):+.2f} | worst: {worst['symbol']} ${float(worst['pnl']):+.2f}")
slips = [float(t["slippage_pct"]) for t in book.trades()
         if t["time"].startswith(day) and t.get("slippage_pct") not in (None, "")]
if slips:
    print(f"avg slippage vs screen: {sum(slips) / len(slips):+.2f}% over {len(slips)} fills (negative = worse)")
if reasons:
    top, n = reasons.most_common(1)[0]
    print(f"most common kill: {top} ({n}x)")
