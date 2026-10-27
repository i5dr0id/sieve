# close_now.py <paper|live> <mint>
# the dashboard's Close button: sell this position NOW, ahead of everything else, in its own process,
# so it never waits for the scan cycle. live: a very high priority fee (max 0.001 SOL) and wider slippage
# on each retry, because getting out matters more than the last few % of price.
# if every try fails, the close request stays and watch.py keeps retrying every minute.
import sys, time
import config, book
from market import pool

SLIPPAGE_LADDER = [500, 1000, 2000]          # bps per try: 5%, then 10%, then 20%
mode, mint = sys.argv[1], sys.argv[2]


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


def price_now() -> float:
    try:
        return (pool(mint) or {}).get("price") or 0.0
    except Exception:
        return 0.0


if config.PAPER:
    p = price_now()
    pnl = book.sell(mint, 1.0, p, "manual_close")
    log(f"{sym}: sold the rest at {(p / pos['entry'] - 1) * 100:+.0f}% (manual_close, priority), pnl ${pnl:+.2f}")
    book.clear_close_request(mint)
    sys.exit(0)

import trade
for i, bps in enumerate(SLIPPAGE_LADDER, 1):
    p = price_now()
    try:
        pnl = trade.leave(mint, 1.0, p, "manual_close", slippage_bps=bps, priority=True, wait=70)
    except book.SellBusy as e:                   # the engine sold it first, or is selling it now
        log(f"{sym}: priority close stood down ({e})")
        break
    except Exception as e:
        log(f"ERROR {sym}: priority close try {i}/{len(SLIPPAGE_LADDER)} at {bps / 100:.0f}% slippage failed: {config.scrub(e)[:160]}")
        continue
    pct = (p / pos["entry"] - 1) * 100 if p else 0
    log(f"{sym}: LIVE sold the rest at {pct:+.0f}% (manual_close, priority, try {i}), pnl ${pnl:+.2f}")
    book.clear_close_request(mint)
    break
