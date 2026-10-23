# verdict.py
# the judge's call on a token that passed every free check.
#   python verdict.py <mint> BUY|SKIP <confidence 0-1> "<why>" [judge]
# judge defaults to "claude"; autojudge.py passes "code".
# limits and the pool re-run at the live price before any paper fill.
import sys, time
from config import MIN_CONFIDENCE, PAPER, TICKET_USD
from market import pool, market_kill
from check import log
import book, followup

mint, verdict, conf, why = sys.argv[1], sys.argv[2].upper(), float(sys.argv[3]), sys.argv[4]
judge = sys.argv[5] if len(sys.argv) > 5 else "claude"
m = pool(mint)
symbol = (m or {}).get("symbol")
if verdict == "BUY" and conf < MIN_CONFIDENCE:
    verdict, why = "SKIP", f"low confidence {conf}"
if verdict == "BUY" and (k := book.guard(mint) or market_kill(m)):
    verdict, why = "SKIP", f"changed since review: {k}"
log({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, "symbol": symbol, "stage": judge,
     "verdict": verdict, "confidence": conf, "reason": why})
if m:
    followup.start(mint, symbol, judge, verdict, m)              # price now, checked again at +6h / +24h
if verdict == "BUY":
    if PAPER:
        book.open_position(mint, symbol, m["price"], m["liq_usd"])
        print(f"PAPER BUY ${TICKET_USD} of {symbol} at {m['price']}")
    else:
        import trade
        try:
            print(trade.enter(mint, symbol, m))
        except Exception as e:
            print(f"ERROR live buy {symbol} failed, nothing recorded: {e}")
else:
    print(f"SKIP {symbol}: {why}")
