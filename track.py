# track.py
# record a token's price and liquidity every minute, with NO position and no money, to see if/when it rugs.
#   python track.py add <mint> <symbol> <our_entry_price> [hours=48]    start tracking
#   python track.py                                                      one tick for everything tracked (run it every minute)
# rows go to logs/tracks/<symbol>_<mint8>.csv. a RUG row is written once, when liquidity falls under 20% of the
# best seen or price under 10% of the best seen. tracking stops after `hours`, or 6h after the rug.
import csv, json, os, re, sys, time
import config
from market import pool

LIST, DIR = "logs/tracking.json", "logs/tracks"
RUG_LIQ, RUG_PRICE, AFTER_RUG_H = 0.20, 0.10, 6
os.makedirs(DIR, exist_ok=True)
FIELDS = ["time", "price", "pct_vs_entry", "liq_usd", "buys_1h", "sells_1h", "vol_1h", "chg_1h", "event"]


def load() -> dict:
    return json.load(open(LIST)) if os.path.exists(LIST) else {}


def save(t: dict):
    json.dump(t, open(LIST + ".tmp", "w"), indent=1); os.replace(LIST + ".tmp", LIST)


def add(mint, symbol, entry, hours=48):
    t = load()
    t[mint] = {"symbol": symbol, "entry": float(entry), "until": time.time() + hours * 3600,
               "peak_price": 0.0, "peak_liq": 0.0, "rugged_at": None}
    save(t)
    print(f"tracking {symbol} {mint[:8]} for {hours}h")


def tick():
    t = load()
    for mint, s in list(t.items()):
        if time.time() > s["until"] or (s["rugged_at"] and time.time() > s["rugged_at"] + AFTER_RUG_H * 3600):
            print(f"{time.strftime('%H:%M')} TRACK {s['symbol']}: done" + (" (rugged)" if s["rugged_at"] else ""))
            del t[mint]; continue
        try:
            m = pool(mint)
        except Exception as e:
            print(f"{time.strftime('%H:%M')} TRACK {s['symbol']}: feed error {config.scrub(e)[:80]}"); continue
        price, liq = (m["price"], m["liq_usd"]) if m else (0.0, 0.0)
        s["peak_price"], s["peak_liq"] = max(s["peak_price"], price), max(s["peak_liq"], liq)
        event = ""
        if not m:
            event = "POOL_GONE"
        if not s["rugged_at"] and s["peak_liq"] > 0 and (not m or liq < s["peak_liq"] * RUG_LIQ or price < s["peak_price"] * RUG_PRICE):
            s["rugged_at"], event = time.time(), "RUG"
            print(f"{time.strftime('%H:%M')} TRACK {s['symbol']}: RUG. price {price:.3g} (best {s['peak_price']:.3g}), "
                  f"liq ${liq:,.0f} (best ${s['peak_liq']:,.0f})")
        path = f"{DIR}/{re.sub('[^A-Za-z0-9]', '', s['symbol']) or 'tok'}_{mint[:8]}.csv"
        new = not os.path.exists(path)
        with open(path, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(FIELDS)
            w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), price, round((price / s["entry"] - 1) * 100, 1) if s["entry"] else "",
                        round(liq), (m or {}).get("buys_1h", ""), (m or {}).get("sells_1h", ""),
                        (m or {}).get("vol_1h", ""), (m or {}).get("chg_1h", ""), event])
    save(t)


if __name__ == "__main__":
    if len(sys.argv) >= 5 and sys.argv[1] == "add":
        add(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]) if len(sys.argv) > 5 else 48)
    else:
        tick()
