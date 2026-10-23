# followup.py
# what every judged token did AFTER the verdict: price now, then +6h and +24h.
# tells you whether the judge's skips were right (they went down) or too strict (they went up).
#   python followup.py          fills in any +6h / +24h checks that are due (run.sh calls it every loop)
import csv, os, time
from config import FOLLOWUPS
from market import pool

FIELDS = ["decided", "hour_local", "hour_ny", "mint", "symbol", "judge", "verdict", "age_min",
          "price0", "liq0", "price_6h", "pct_6h", "price_24h", "pct_24h"]
CHECKPOINTS = [("6h", 6 * 3600), ("24h", 24 * 3600)]


def _rows() -> list[dict]:
    return list(csv.DictReader(open(FOLLOWUPS))) if os.path.exists(FOLLOWUPS) else []


def _write(rows: list[dict]):
    tmp = FOLLOWUPS + ".tmp"
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, FOLLOWUPS)


def start(mint, symbol, judge, verdict, m: dict):
    now = time.time()
    ny = time.strftime("%H", time.gmtime(now - 4 * 3600))      # New York, EDT (UTC-4)
    rows = _rows()
    rows.append({"decided": time.strftime("%Y-%m-%d %H:%M", time.localtime(now)),
                 "hour_local": time.strftime("%H", time.localtime(now)), "hour_ny": ny,
                 "mint": mint, "symbol": symbol, "judge": judge, "verdict": verdict,
                 "age_min": m.get("age_min"), "price0": m["price"], "liq0": m["liq_usd"]})
    _write(rows)


def update() -> list[str]:
    rows, events, changed = _rows(), [], False
    for r in rows:
        decided = time.mktime(time.strptime(r["decided"], "%Y-%m-%d %H:%M"))
        for name, secs in CHECKPOINTS:
            if r.get(f"price_{name}") or time.time() - decided < secs:
                continue
            try:
                m = pool(r["mint"])
            except Exception:
                continue                                         # source down: try again next loop
            price = (m or {}).get("price") or 0                  # pool gone counts as 0 (rugged)
            r[f"price_{name}"] = price
            r[f"pct_{name}"] = round((price / float(r["price0"]) - 1) * 100, 1)
            changed = True
            events.append(f"FOLLOWUP {r['symbol']} ({r['judge']} {r['verdict']}) {name}: {r[f'pct_{name}']:+}%")
    if changed:
        _write(rows)
    return events


if __name__ == "__main__":
    for e in update():
        print(e)
