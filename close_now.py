# close_now.py <paper|live> <mint> [part]
# the dashboard's Close and Sell-half buttons: sell NOW, ahead of everything else, in its own process,
# so it never waits for the scan cycle. live: a very high priority fee (max 0.001 SOL) and wider slippage
# on each retry, because getting out matters more than the last few % of price.
#   part: 1 (default) = everything; 0.5 = half of what is held right now.
# a full close that fails every try stays requested, and watch.py keeps retrying every minute.
# a half sale is never handed to that retry (it would sell everything): it logs the failure instead.
import sys, time
import config, book
from market import pool

SLIPPAGE_LADDER = [500, 1000, 2000]          # bps per try: 5%, then 10%, then 20%
mode, mint = sys.argv[1], sys.argv[2]
part = min(1.0, max(0.05, float(sys.argv[3]))) if len(sys.argv) > 3 else 1.0
full = part >= 1
why = "manual_close" if full else "manual_half"


def log(msg: str):
    line = f"{time.strftime('%H:%M')} WATCH {msg}"
    print(line, flush=True)
    with open(config.SESSION_LOG, "a") as f:
        f.write(line + "\n")


if mode != config.MODE:
    sys.exit(f"{time.strftime('%H:%M')} the desk is running {config.MODE}, not {mode}: left for the engine")
pos = book.load().get(mint)
if not pos:
    sys.exit(0)
sym = pos["symbol"]
frac = 1.0 if full else part * pos["qty"] / pos["qty0"]      # the book and trade.leave count in fractions of the ORIGINAL size
what = "the rest" if full else f"{int(part * 100)}% of what was left"


def price_now() -> float:
    try:
        return (pool(mint) or {}).get("price") or 0.0
    except Exception:
        return 0.0


def done(pnl: float, p: float, extra: str = ""):
    pct = (p / pos["entry"] - 1) * 100 if p else 0
    log(f"{sym}: {'sold' if config.PAPER else 'LIVE sold'} {what} at {pct:+.0f}% ({why}, priority{extra}), pnl ${pnl:+.2f}")
    if full:
        book.clear_close_request(mint)


if config.PAPER:
    p = price_now()
    done(book.sell(mint, frac, p, why), p)
    sys.exit(0)

import trade
for i, bps in enumerate(SLIPPAGE_LADDER, 1):
    p = price_now()
    try:
        pnl = trade.leave(mint, frac, p, why, slippage_bps=bps, priority=True, wait=70)
    except book.SellBusy as e:                   # the engine sold it first, or is selling it now
        log(f"{sym}: priority {'close' if full else 'half sale'} stood down ({e})")
        break
    except Exception as e:
        log(f"ERROR {sym}: priority {'close' if full else 'half sale'} try {i}/{len(SLIPPAGE_LADDER)} at {bps / 100:.0f}% slippage failed: {config.scrub(e)[:160]}")
        continue
    done(pnl, p, f", try {i}")
    break
