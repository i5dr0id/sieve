# watch.py
# every open position, every 10 minutes. prints nothing when nothing changed.
import time
from config import EXIT, PAPER
from market import pool
import book
if not PAPER:
    import trade


def watch() -> list[str]:
    events = []
    manual = book.close_requests()
    for mint, p in list(book.load().items()):
        try:
            m = pool(mint)
        except Exception as e:
            events.append(f"{p['symbol']}: price feed down ({e}), holding, will retry")
            continue
        if not m or m["price"] <= 0:
            if PAPER:
                events.append(f"{p['symbol']}: pool gone. treat as rugged")
                book.sell(mint, 1.0, 0.0, "pool_gone")
            else:
                try:
                    pnl = trade.leave(mint, 1.0, 0.0, "pool_gone")
                    events.append(f"{p['symbol']}: pool gone, sold what was left, pnl ${pnl:+.2f}")
                except Exception as e:
                    events.append(f"ERROR {p['symbol']}: pool gone and sell failed ({e}), retry next run")
            continue

        price = m["price"]
        with book.edit() as b:                           # under the book lock: never overwrites a sale made elsewhere
            if mint not in b:                            # closed meanwhile (a Close button, another exit)
                continue
            s = b[mint]
            s["peak"] = max(s["peak"], price)
        s = dict(s)
        pct = (price / s["entry"] - 1) * 100
        hours = (time.time() - s["opened"]) / 3600

        def out(frac, why, **live) -> bool:
            size = "the rest" if frac >= 1 else f"{int(frac * 100)}%"
            try:
                pnl = book.sell(mint, frac, price, why) if PAPER else trade.leave(mint, frac, price, why, **live)
            except book.SellBusy:                        # another sell of this token is running. next run looks again
                return False
            except Exception as e:                       # position stays in the book, next run retries
                events.append(f"ERROR {s['symbol']}: live sell {size} ({why}) failed: {e}")
                return False
            events.append(f"{s['symbol']}: {'sold' if PAPER else 'LIVE sold'} {size} at {pct:+.0f}% ({why}), pnl ${pnl:+.2f}")
            return True

        if mint in manual:                               # the dashboard's Close button. a failed sell stays requested and retries
            if out(1.0, "manual_close", slippage_bps=1000, priority=True):
                book.clear_close_request(mint)
            continue
        if m["liq_usd"] < s["liq0"] * (1 - EXIT["liq_drop_pct"] / 100):
            out(1.0, "liquidity_drop"); continue
        if pct <= EXIT["stop_pct"]:
            out(1.0, "stop"); continue
        ladder = EXIT["ladder"]
        if s["steps"] < len(ladder) and pct >= ladder[s["steps"]][0]:
            if not out(ladder[s["steps"]][1], f"take_profit_{ladder[s['steps']][0]}"):
                continue
            with book.edit() as b:
                if mint in b:
                    b[mint]["steps"] += 1
            continue
        if s["steps"] > 0 and price <= s["peak"] * (1 - EXIT["trail_pct"] / 100):
            out(1.0, "trailing_stop"); continue
        # past the time stop and still up: trail tighter so a slow +20..+100% winner can't sit forever and round-trip
        if s["steps"] == 0 and hours >= EXIT["time_stop_hours"] and price <= s["peak"] * (1 - EXIT["late_trail_pct"] / 100):
            out(1.0, "late_trail"); continue
        if hours >= EXIT["time_stop_hours"] and pct < EXIT["time_stop_min_pct"]:
            out(1.0, "time_stop")
    book.clear_close_request()                            # forget requests for positions that are already gone
    return events


if __name__ == "__main__":
    for e in watch():
        print(e)
