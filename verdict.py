# verdict.py
# the judge's call on a token that passed every free check.
#   python verdict.py <mint> BUY|SKIP <confidence 0-1> "<why>" [judge]
# judge defaults to "claude"; autojudge.py passes "code".
# the pool re-runs at the live price before a BUY counts. each mode then checks its own limits (enter.py).
import sys, time
from config import MIN_CONFIDENCE
from market import pool, market_kill
from check import log
import followup
from fills import enter_both

mint, verdict, conf, why = sys.argv[1], sys.argv[2].upper(), float(sys.argv[3]), sys.argv[4]
judge = sys.argv[5] if len(sys.argv) > 5 else "claude"
m = pool(mint)
symbol = (m or {}).get("symbol")
if verdict == "BUY" and conf < MIN_CONFIDENCE:
    verdict, why = "SKIP", f"low confidence {conf}"
if verdict == "BUY" and (k := market_kill(m)):
    verdict, why = "SKIP", f"changed since review: {k}"
log({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, "symbol": symbol, "stage": judge,
     "verdict": verdict, "confidence": conf, "reason": why})
if m:
    followup.start(mint, symbol, judge, verdict, m)              # price now, checked again at +6h / +24h
if verdict == "BUY":
    print("\n".join(enter_both(mint, symbol, m["price"], m["liq_usd"])))
else:
    print(f"SKIP {symbol}: {why}")
