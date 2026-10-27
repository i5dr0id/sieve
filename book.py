# book.py
# positions, trades, limits. the desk's memory lives in two files you can open yourself.
import contextlib, csv, fcntl, json, os, sys, time
import config
from config import (POSITIONS, TRADES, TICKET_USD, MAX_OPEN, MAX_ENTRIES_PER_DAY,
                    DAILY_LOSS_HALT_USD, COOLDOWN_HOURS, PAPER)


def load() -> dict:
    return json.load(open(POSITIONS)) if os.path.exists(POSITIONS) else {}


def save(book: dict):
    json.dump(book, open(POSITIONS, "w"), indent=2)


class SellBusy(Exception):
    """another sell of this token is already running (or it just closed). nothing was sent."""


@contextlib.contextmanager
def sell_lock(mint: str, wait: float = 0):
    """one sell per token at a time. a second seller waits up to `wait` seconds, then raises SellBusy.
    the OS drops the lock when the process ends, so a crash can never leave a token stuck."""
    f = open(os.path.join(os.path.dirname(POSITIONS), f"sell_{mint[:12]}.lock"), "w")
    end = time.time() + wait
    while True:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.time() >= end:
                f.close()
                raise SellBusy(f"a sell of {mint[:8]} is already running")
            time.sleep(0.5)
    try:
        yield
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


CLOSE_REQ = os.path.join(os.path.dirname(POSITIONS), "close_requests.json")


def close_requests() -> set:
    """mints the user asked to close from the dashboard's Close button. watch.py sells them on its next check."""
    try:
        return set(json.load(open(CLOSE_REQ)))
    except Exception:
        return set()


def clear_close_request(mint=None):
    """drop one request, or (no mint) every request for a position that is no longer open."""
    left = {m for m in close_requests() if mint is not None and m != mint and m in load()} if mint else \
           {m for m in close_requests() if m in load()}
    if left:
        json.dump(sorted(left), open(CLOSE_REQ, "w"))
    elif os.path.exists(CLOSE_REQ):
        os.remove(CLOSE_REQ)


def trades() -> list[dict]:
    return list(csv.DictReader(open(TRADES))) if os.path.exists(TRADES) else []


FIELDS = ["time", "mode", "mint", "symbol", "action", "usd", "pnl", "reason",
          "price", "qty", "screen_price", "slippage_pct", "tx"]


def record(mint, symbol, action, usd, pnl, reason, price=None, qty=None, screen_price=None, tx=None):
    """price = what you actually got per token, screen_price = what DexScreener showed.
    slippage_pct is the gap, negative = the fill was worse than the screen."""
    if os.path.exists(TRADES):
        with open(TRADES) as f:
            if next(csv.reader(f), []) != FIELDS:            # old format: keep it, start a fresh file
                os.rename(TRADES, TRADES.replace(".csv", f"_old_{int(time.time())}.csv"))
    new = not os.path.exists(TRADES)
    screen_price = screen_price or price
    slip = None
    if price and screen_price:
        worse = price > screen_price if action == "open" else price < screen_price
        slip = round(-abs(price / screen_price - 1) * 100 if worse else abs(price / screen_price - 1) * 100, 2)
    with open(TRADES, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({"time": time.strftime("%Y-%m-%d %H:%M"), "mode": "paper" if PAPER else "live",
                    "mint": mint, "symbol": symbol, "action": action, "usd": round(usd, 2),
                    "pnl": round(pnl, 2), "reason": reason, "price": price, "qty": qty,
                    "screen_price": screen_price, "slippage_pct": slip,
                    "tx": f"https://solscan.io/tx/{tx}" if tx else ""})


def today_pnl(day: str | None = None) -> float:
    day = day or time.strftime("%Y-%m-%d")
    return sum(float(t["pnl"]) for t in trades() if t["time"].startswith(day))


def guard(mint: str) -> str | None:
    """Limits run before any network call. A blocked entry costs nothing."""
    day = time.strftime("%Y-%m-%d")
    book = load()
    if config.buys_paused():                                     return "paused"
    if config.HALT_CARRYOVER:                                    return "waiting_for_live"
    if not PAPER and today_pnl() <= -DAILY_LOSS_HALT_USD:        return "halted_daily_loss"
    if mint in book:                                             return "already_open"
    if len(book) >= MAX_OPEN:                                    return "max_open"
    opens = [t for t in trades() if t["action"] == "open" and t["time"].startswith(day)]
    if len(opens) >= MAX_ENTRIES_PER_DAY:                        return "max_entries_today"
    cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - COOLDOWN_HOURS * 3600))
    if any(t["mint"] == mint and t["action"] == "close" and t["time"] >= cutoff for t in trades()):
        return "cooldown"
    return None


def open_position(mint, symbol, price, liq_usd, usd=TICKET_USD, screen_price=None, tx=None):
    book = load()
    book[mint] = {"symbol": symbol, "entry": price, "qty0": usd / price, "qty": usd / price,
                  "peak": price, "liq0": liq_usd, "opened": time.time(), "steps": 0}
    save(book)
    record(mint, symbol, "open", usd, 0, "entry", price, usd / price, screen_price, tx)


def sell(mint, frac_of_original, price, reason, screen_price=None, tx=None) -> float:
    """Sells a fraction of the ORIGINAL size (1.0 = everything left). Returns realized pnl."""
    book = load()
    p = book[mint]
    q = min(p["qty"], p["qty0"] * frac_of_original)
    pnl = q * (price - p["entry"])
    p["qty"] -= q
    action = "close" if p["qty"] <= p["qty0"] * 1e-6 else "partial"
    record(mint, p["symbol"], action, q * price, pnl, reason, price, q, screen_price, tx)
    if action == "close":
        del book[mint]
    save(book)
    return pnl


if __name__ == "__main__":
    # live mode: after you buy in your own wallet ->  python book.py add <mint> <usd> <price> <liq_usd>
    # after you sell by hand                     ->  python book.py close <mint> <price>
    cmd = sys.argv[1]
    if cmd == "add":
        mint, usd, price, liq = sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5])
        open_position(mint, mint[:6], price, liq, usd)
    elif cmd == "close":
        print(round(sell(sys.argv[2], 1.0, float(sys.argv[3]), "manual"), 2))
