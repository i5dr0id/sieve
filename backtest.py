# backtest.py
# replays every token Sieve has already checked against what its price actually did afterwards.
# price history: GeckoTerminal 5-minute candles (free, ~30 calls/min, cached in logs/cache/).
#   python backtest.py              fetch what's missing, then report
#   python backtest.py --offline    report from cache only
#
# what it answers:
#   1. were the kills right?  what killed tokens did in the 24h after we killed them, per kill reason
#   2. what if we bought everything that passed the 13 checks, with our exit rules?
#   3. which exit settings would have done best?
# what it can't do: the liquidity-pulled exit (no liquidity history), and tokens whose pool vanished
# entirely are reported as "no data" - many of those are rugs, so results lean optimistic.
import csv, json, os, statistics, sys, time
from collections import defaultdict
import requests
from config import LOG, EXIT, TICKET_USD, ENV

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
CG = "https://api.coingecko.com/api/v3/onchain/networks/solana"   # same data, used only when GT rate-limits
CG_KEY = ENV.get("COINGECKO_API_KEY")                             # free demo key: ~10k calls a month
CACHE = "logs/cache/geckoterminal"
COST_PCT = 5            # assumed round-trip cost (fees + slippage) on every simulated trade
HORIZON_H = 24
os.makedirs(CACHE, exist_ok=True)
_last_call = [0.0]


def _get(url, params=None):
    wait = 2.2 - (time.time() - _last_call[0])              # stay under ~30 calls/min
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        _last_call[0] = time.time()
        r = requests.get(url, params=params, timeout=20, headers={"Accept": "application/json"})
        if r.status_code == 429 and CG_KEY:                          # GT busy: same request via CoinGecko
            r = requests.get(url.replace(GT, CG), params=params, timeout=20,
                             headers={"Accept": "application/json", "x-cg-demo-api-key": CG_KEY})
        if r.status_code == 429:
            time.sleep(15 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()
    raise RuntimeError("rate limited")


def candles(mint: str, offline: bool) -> list | None:
    """5-min candles [ts, o, h, l, c, v], oldest first. None = no data."""
    path = f"{CACHE}/{mint}.json"
    if os.path.exists(path):
        d = json.load(open(path))
        if d.get("complete") or offline:
            return d.get("ohlcv")
    if offline:
        return None
    pools = _get(f"{GT}/tokens/{mint}/pools", {"page": 1})
    data = (pools or {}).get("data") or []
    if not data:
        ohlcv = None
    else:
        pool = data[0]["attributes"]["address"]
        o = _get(f"{GT}/pools/{pool}/ohlcv/minute", {"aggregate": 5, "limit": 1000, "currency": "usd", "token": "base"})
        ohlcv = sorted(((o or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or [])
    # a token checked < 24h ago is cached as incomplete so a later run extends it
    json.dump({"ohlcv": ohlcv, "complete": False, "fetched": time.time()}, open(path, "w"))
    return ohlcv


def mark_complete(mint, t0):
    path = f"{CACHE}/{mint}.json"
    if os.path.exists(path) and time.time() - t0 > HORIZON_H * 3600:
        d = json.load(open(path)); d["complete"] = True; json.dump(d, open(path, "w"))


def window(c, t0):
    """Candles from the decision time to +24h. Entry = close of the candle that contains t0."""
    before = [x for x in c if x[0] <= t0]
    after = [x for x in c if t0 < x[0] <= t0 + HORIZON_H * 3600]
    if not before or not after or before[-1][4] <= 0:
        return None, None
    return before[-1][4], after


def simulate(entry, path, stop=EXIT["stop_pct"], ladder=tuple(EXIT["ladder"]), trail=EXIT["trail_pct"],
             tstop_h=EXIT["time_stop_hours"], tstop_min=EXIT["time_stop_min_pct"]):
    """Our exit rules on candles. Pessimistic: inside a candle the low is checked before the high."""
    left, pnl, steps, peak, t_open = 1.0, 0.0, 0, entry, path[0][0] - 300
    for ts, o, h, l, cl, v in path:
        if (l / entry - 1) * 100 <= stop and steps == 0:            # hard stop (before first take)
            px = entry * (1 + stop / 100)
            return pnl + left * (px / entry - 1), "stop"
        if steps > 0 and l <= peak * (1 - trail / 100):              # trailing stop (after first take)
            px = peak * (1 - trail / 100)
            return pnl + left * (px / entry - 1), "trailing_stop"
        peak = max(peak, h)
        while steps < len(ladder) and (h / entry - 1) * 100 >= ladder[steps][0]:
            frac = min(left, ladder[steps][1])
            pnl += frac * (ladder[steps][0] / 100)
            left -= frac; steps += 1
        if (ts - t_open) / 3600 >= tstop_h and steps == 0 and (cl / entry - 1) * 100 < tstop_min:
            return pnl + left * (cl / entry - 1), "time_stop"
    return pnl + left * (path[-1][4] / entry - 1), "held_24h"


def ret(frac):                     # fraction of ticket -> dollars after costs
    return TICKET_USD * (frac - COST_PCT / 100)


def main():
    offline = "--offline" in sys.argv
    rows = list(csv.DictReader(open(LOG)))
    first = {}
    for r in rows:                                                   # one entry per mint: its final verdict
        if "failed:" in (r["reason"] or ""):
            continue
        t = time.mktime(time.strptime(r["time"], "%Y-%m-%d %H:%M"))
        f = first.setdefault(r["mint"], {"mint": r["mint"], "symbol": r["symbol"], "t0": t})
        if r["stage"] in ("claude", "grok", "code"):
            f["judge"] = r["verdict"]
        elif r["verdict"] == "REVIEW":
            f["group"] = "passed 13 checks"
        else:
            f["group"] = f"{r['stage']}: {r['reason']}"
    tokens = [f for f in first.values() if time.time() - f["t0"] > 3600]   # need at least 1h of after-data
    print(f"{len(tokens)} tokens to replay ({len(first) - len(tokens)} too recent). fetching price history...", flush=True)

    out = []
    for i, f in enumerate(tokens, 1):
        try:
            c = candles(f["mint"], offline)
        except Exception as e:
            print(f"  {f['symbol']}: fetch failed ({e})", flush=True); c = None
        if i % 25 == 0:
            print(f"  {i}/{len(tokens)}", flush=True)
        entry, path = window(c, f["t0"]) if c else (None, None)
        if entry is None:
            out.append({**f, "data": False}); continue
        mark_complete(f["mint"], f["t0"])
        hi = max(x[2] for x in path); lo = min(x[3] for x in path)
        sim, why = simulate(entry, path)
        out.append({**f, "data": True, "entry": entry, "hours": len(path) / 12,
                    "max_pct": (hi / entry - 1) * 100, "min_pct": (lo / entry - 1) * 100,
                    "end_pct": (path[-1][4] / entry - 1) * 100, "sim": sim, "exit": why})

    with open(LOG.replace("checks.csv", "backtest.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["mint", "symbol", "group", "judge", "data", "entry", "hours",
                                           "max_pct", "min_pct", "end_pct", "sim", "exit", "t0"], extrasaction="ignore")
        w.writeheader(); w.writerows(out)

    have = [o for o in out if o["data"]]
    print(f"\nprice data for {len(have)}/{len(out)} tokens. no data (pool gone or never indexed): {len(out) - len(have)}")
    print(f"costs assumed: {COST_PCT}% per round trip. horizon: {HORIZON_H}h after our check. paper ticket ${TICKET_USD}.\n")

    # 1. were the kills right?
    groups = defaultdict(list)
    for o in out:
        groups[o.get("group", "?")].append(o)
    print("1. WHAT EACH GROUP DID AFTER WE CHECKED IT (24h)")
    print(f"{'group':44} {'n':>4} {'data':>5} {'hit+100%':>9} {'fell-80%':>9} {'median end':>11} {'our exits $/trade':>18}")
    for g, lst in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        d = [o for o in lst if o["data"]]
        if not d:
            print(f"{g[:44]:44} {len(lst):>4} {0:>5}"); continue
        hit = sum(o["max_pct"] >= 100 for o in d) / len(d) * 100
        dead = sum(o["min_pct"] <= -80 for o in d) / len(d) * 100
        med = statistics.median(o["end_pct"] for o in d)
        avg = statistics.mean(ret(o["sim"]) for o in d)
        print(f"{g[:44]:44} {len(lst):>4} {len(d):>5} {hit:>8.0f}% {dead:>8.0f}% {med:>+10.0f}% {avg:>+17.2f}")

    # 2. buy everything that passed the 13 checks
    passed = [o for o in have if o.get("group") == "passed 13 checks"]
    print("\n2. IF WE HAD BOUGHT EVERY TOKEN THAT PASSED THE 13 CHECKS (no judge)")
    if passed:
        tot = sum(ret(o["sim"]) for o in passed)
        for o in sorted(passed, key=lambda o: -o["sim"]):
            print(f"   {o['symbol'] or o['mint'][:6]:14} judge={o.get('judge', '-'):5} max {o['max_pct']:+7.0f}%  "
                  f"exit {o['exit']:14} ${ret(o['sim']):+7.2f}")
        judged_buy = [o for o in passed if o.get("judge") == "BUY"]
        print(f"   total ${tot:+.2f} over {len(passed)} trades (${tot / len(passed):+.2f}/trade)."
              f" judge's buys only: ${sum(ret(o['sim']) for o in judged_buy):+.2f} over {len(judged_buy)}")
    else:
        print("   none with price data yet")

    # 3. exit-rule sweep on a wider sample: everything that passed the CONTRACT checks
    #    (killed only at pool stage, or passed) - more trades, so the comparison means something
    sample = [o for o in have if o.get("group", "").startswith("pool") or o.get("group") == "passed 13 checks"]
    print(f"\n3. EXIT SETTINGS COMPARED on {len(sample)} contract-clean tokens ($/trade after costs)")
    if len(sample) >= 5:
        res = []
        for stop in (-20, -35, -50):
            for trail in (20, 30, 40):
                for tst in (3, 6, 12):
                    tot = 0.0
                    for o in sample:
                        c = json.load(open(f"{CACHE}/{o['mint']}.json"))["ohlcv"]
                        entry, path = window(c, o["t0"])
                        tot += ret(simulate(entry, path, stop=stop, trail=trail, tstop_h=tst)[0])
                    res.append((tot / len(sample), stop, trail, tst))
        res.sort(reverse=True)
        cur = next(r for r in res if (r[1], r[2], r[3]) == (EXIT["stop_pct"], EXIT["trail_pct"], EXIT["time_stop_hours"]))
        print(f"   current config (stop {cur[1]}%, trail {cur[2]}%, time stop {cur[3]}h): ${cur[0]:+.2f}/trade")
        for avg, s, t, ts in res[:5]:
            print(f"   stop {s:>4}%  trail {t}%  time stop {ts:>2}h   ${avg:+.2f}/trade")
        print(f"   worst: stop {res[-1][1]}% trail {res[-1][2]}% time {res[-1][3]}h  ${res[-1][0]:+.2f}/trade")
    else:
        print("   not enough tokens yet")


if __name__ == "__main__":
    main()
