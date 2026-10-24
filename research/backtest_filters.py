# research/backtest_filters.py
# replays every token that passed the 13 checks and asks: what would the proposed new filters have removed,
# and were the removed ones losers? exits are watch.py's rules on GeckoTerminal 5-minute candles.
#   python research/backtest_filters.py [logs_dir ...]     default: logs/phone_snapshot/live logs/phone_snapshot/paper
# read-only: public price data, no wallet, no trading.
import ast, csv, json, os, re, statistics, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
CACHE = "logs/cache/gt_at"           # candles ending 25h after the check, so the hour BEFORE the check is in them too
TICKET, COST_PCT, HORIZON_H = 5, 5, 24
os.makedirs(CACHE, exist_ok=True)
_last = [0.0]


def _get(url, params=None):
    for attempt in range(5):
        wait = 2.2 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        r = requests.get(url, params=params, timeout=20, headers={"Accept": "application/json"})
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1)); continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited")


def candles(mint, t0):
    path = f"{CACHE}/{mint}.json"
    if os.path.exists(path):
        d = json.load(open(path))
        if d.get("complete"):
            return d["ohlcv"]
    pools = ((_get(f"{GT}/tokens/{mint}/pools", {"page": 1}) or {}).get("data")) or []
    ohlcv = None
    if pools:
        before = int(min(time.time(), t0 + (HORIZON_H + 1) * 3600))
        o = _get(f"{GT}/pools/{pools[0]['attributes']['address']}/ohlcv/minute",
                 {"aggregate": 5, "limit": 1000, "currency": "usd", "token": "base", "before_timestamp": before})
        ohlcv = sorted(((o or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or [])
    json.dump({"ohlcv": ohlcv, "complete": time.time() > t0 + (HORIZON_H + 1) * 3600}, open(path, "w"))
    return ohlcv


def fill(trigger, low):
    """a stop fills at its trigger, unless the candle crashed through it (low under half the trigger):
    then assume we got the low, like DOAS did. a 1-minute checker can't sell inside a 5-minute crash."""
    return trigger if low >= trigger * 0.5 else low


def simulate(entry, path, stop=-35, ladder=((100, 0.5), (200, 0.25)), trail=30, late_trail=20, tstop_h=4, tstop_min=20):
    left, pnl, steps, peak, t_open = 1.0, 0.0, 0, entry, path[0][0] - 300
    for ts, o, h, l, cl, v in path:
        hours = (ts - t_open) / 3600
        if (l / entry - 1) * 100 <= stop:
            return pnl + left * (fill(entry * (1 + stop / 100), l) / entry - 1), "stop"
        if steps > 0 and l <= peak * (1 - trail / 100):
            return pnl + left * (fill(peak * (1 - trail / 100), l) / entry - 1), "trailing_stop"
        if late_trail and steps == 0 and hours >= tstop_h and l <= peak * (1 - late_trail / 100):
            return pnl + left * (fill(peak * (1 - late_trail / 100), l) / entry - 1), "late_trail"
        peak = max(peak, h)
        while steps < len(ladder) and (h / entry - 1) * 100 >= ladder[steps][0]:
            frac = min(left, ladder[steps][1]); pnl += frac * ladder[steps][0] / 100; left -= frac; steps += 1
        if hours >= tstop_h and steps == 0 and (cl / entry - 1) * 100 < tstop_min:
            return pnl + left * (cl / entry - 1), "time_stop"
    return pnl + left * (path[-1][4] / entry - 1), "held_24h"


usd = lambda frac: TICKET * (frac - COST_PCT / 100)
REV = re.compile(r"REVIEW (\S+) (\S+) .*?liq=\$([\d,]+) .*?top10=([\d.]+)% .*?warn=(\[.*\])")


def load(dirs):
    toks = {}
    for d in dirs:
        rows = list(csv.DictReader(open(f"{d}/checks.csv")))
        when = {r["mint"]: r["time"] for r in rows if r["verdict"] == "REVIEW"}
        judge = {}
        for r in rows:
            if r["stage"] in ("claude", "grok", "code") and "failed:" not in (r["reason"] or ""):
                judge[r["mint"]] = r["verdict"]
        for line in open(f"{d}/session.log"):
            m = REV.search(line)
            if not m or m.group(1) not in when or m.group(1) in toks:
                continue
            mint = m.group(1)
            toks[mint] = {"mint": mint, "symbol": m.group(2), "liq": float(m.group(3).replace(",", "")),
                          "top10": float(m.group(4)), "warn": ast.literal_eval(m.group(5)),
                          "t0": time.mktime(time.strptime(when[mint], "%Y-%m-%d %H:%M")),
                          "judge": judge.get(mint, "-"), "src": os.path.basename(d)}
    return list(toks.values())


def main():
    dirs = sys.argv[1:] or ["logs/phone_snapshot/live", "logs/phone_snapshot/paper"]
    toks = [t for t in load(dirs) if time.time() - t["t0"] > 4 * 3600]     # need at least 4h of after-data
    print(f"{len(toks)} tokens passed the 13 checks (and are 4h+ old). fetching candles...", flush=True)
    have = []
    for t in toks:
        try:
            c = candles(t["mint"], t["t0"])
        except Exception as e:
            print(f"  {t['symbol']}: fetch failed ({type(e).__name__})"); continue
        before = [x for x in (c or []) if x[0] <= t["t0"]]
        after = [x for x in (c or []) if t["t0"] < x[0] <= t["t0"] + HORIZON_H * 3600]
        if not before or not after or before[-1][4] <= 0:
            continue
        entry = before[-1][4]
        t.update(entry=entry, path=after,
                 vol1h=sum(x[5] for x in c if t["t0"] - 3600 < x[0] <= t["t0"]),
                 max_pct=(max(x[2] for x in after) / entry - 1) * 100,
                 min_pct=(min(x[3] for x in after) / entry - 1) * 100)
        t["v2l"] = t["vol1h"] / t["liq"] if t["liq"] else 0
        t["sim"], t["exit"] = simulate(entry, after)
        t["sim6"], _ = simulate(entry, after, tstop_h=6, late_trail=None)       # the rules before today
        have.append(t)
    print(f"price data for {len(have)}/{len(toks)}  (no data = pool gone or never indexed; many of those are rugs)")
    print(f"exits: stop -35, ladder +100/+200, trail 30, late trail 20 after 4h, time stop 4h<+20. "
          f"${TICKET} ticket, {COST_PCT}% costs. crash candles fill at the low.\n")

    def line(name, lst):
        if not lst:
            return f"{name:42}    0"
        crash = sum(t["min_pct"] <= -80 for t in lst); moon = sum(t["max_pct"] >= 100 for t in lst)
        tot = sum(usd(t["sim"]) for t in lst)
        return f"{name:42} {len(lst):>4}  crashed-80%: {crash:>3}  hit+100%: {moon:>3}   ${tot:+7.2f} total  ${tot / len(lst):+.2f}/trade"

    print("0. THE TIME STOP CHANGE (all tokens with data)")
    print(f"   old rules (6h, no late trail): ${sum(usd(t['sim6']) for t in have):+.2f}   "
          f"new rules (4h + late trail): ${sum(usd(t['sim']) for t in have):+.2f}   over {len(have)} trades\n")

    rules = {"1 holder correlation warning": lambda t: "High holder correlation" in t["warn"]}
    for x in (1, 2, 3):
        rules[f"2 top10 under {x}%"] = lambda t, x=x: t["top10"] < x
    for y in (0.05, 0.1, 0.2, 0.3):
        rules[f"4 1h volume under {y}x the pool"] = lambda t, y=y: t["v2l"] < y

    for label, pop in (("ALL TOKENS THAT PASSED THE 13 CHECKS", have),
                       ("ONLY THE ONES THE JUDGE BOUGHT", [t for t in have if t["judge"] == "BUY"])):
        print(label)
        print("   " + line("baseline (no new rule)", pop))
        for name, f in rules.items():
            cut = [t for t in pop if f(t)]
            print("   removes " + line(name, cut))
        print()

    combo = lambda t: "High holder correlation" in t["warn"] or t["top10"] < 2 or t["v2l"] < 0.1
    for label, pop in (("COMBINED (1 + top10<2% + volume<0.1x), all passes", have),
                       ("COMBINED, judge's buys only", [t for t in have if t["judge"] == "BUY"])):
        kept = [t for t in pop if not combo(t)]
        print(label)
        print("   before: " + line("", pop).strip())
        print("   after:  " + line("", kept).strip())
    print("\nEVERY TOKEN (judge, top10, warn, 1h vol/pool, max, min, result with new exits)")
    for t in sorted(have, key=lambda t: t["sim"]):
        flags = ("C" if "High holder correlation" in t["warn"] else "-") + ("F" if t["top10"] < 2 else "-") + ("V" if t["v2l"] < 0.1 else "-")
        print(f"   {t['symbol'][:12]:12} {t['judge']:4} top10 {t['top10']:5.2f}%  v/l {t['v2l']:5.2f}  {flags}  "
              f"max {t['max_pct']:+6.0f}%  min {t['min_pct']:+5.0f}%  {t['exit']:13} ${usd(t['sim']):+6.2f}")
    print("   flags: C = correlation warning, F = top10 under 2%, V = 1h volume under 0.1x pool")


if __name__ == "__main__":
    main()
