# research/backtest_judge.py
# replays the code judge on every token that passed the 13 checks, with the 1h volume/pool cap at different
# levels (or off), plus the new filters, and sweeps the time stop. uses backtest_filters' candles and exits.
#   python research/backtest_judge.py [logs_dir ...]
# read-only: public price data, no wallet, no trading.
import csv, json, os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import requests
from backtest_filters import load, candles, simulate, usd, HORIZON_H

WEB_CACHE = "logs/cache/websites.json"
BS = re.compile(r"REVIEW (\S+) .*?b/s1h=(\d+)/(\d+)")


def websites(mints):
    have = json.load(open(WEB_CACHE)) if os.path.exists(WEB_CACHE) else {}
    todo = [m for m in mints if m not in have]
    for i in range(0, len(todo), 30):                        # dexscreener takes 30 mints per call
        for p in requests.get("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(todo[i:i + 30]), timeout=20).json():
            m = p["baseToken"]["address"]
            have[m] = have.get(m) or bool((p.get("info") or {}).get("websites"))
        for m in todo[i:i + 30]:
            have.setdefault(m, False)
    json.dump(have, open(WEB_CACHE, "w"))
    return have


def main():
    dirs = sys.argv[1:] or ["logs/phone_snapshot/live", "logs/phone_snapshot/paper"]
    toks = [t for t in load(dirs) if time.time() - t["t0"] > 4 * 3600]
    bs, checks = {}, []
    for d in dirs:
        for line in open(f"{d}/session.log"):
            if (m := BS.search(line)):
                bs.setdefault(m.group(1), (int(m.group(2)), int(m.group(3))))
        checks += list(csv.DictReader(open(f"{d}/checks.csv")))
    web = websites([t["mint"] for t in toks])
    have = []
    for t in toks:
        c = candles(t["mint"], t["t0"])
        before = [x for x in (c or []) if x[0] <= t["t0"]]
        after = [x for x in (c or []) if t["t0"] < x[0] <= t["t0"] + HORIZON_H * 3600]
        if not before or not after or before[-1][4] <= 0:
            continue
        t.update(entry=before[-1][4], path=after, v2l=sum(x[5] for x in c if t["t0"] - 3600 < x[0] <= t["t0"]) / t["liq"],
                 buys=bs.get(t["mint"], (0, 0))[0], sells=bs.get(t["mint"], (0, 0))[1], web=web.get(t["mint"], False))
        t["max_pct"] = (max(x[2] for x in after) / t["entry"] - 1) * 100
        cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(t["t0"] - 24 * 3600))
        now = time.strftime("%Y-%m-%d %H:%M", time.localtime(t["t0"]))
        t["copycat"] = any((r["symbol"] or "").lower() == t["symbol"].lower() and r["mint"] != t["mint"]
                           and cutoff <= r["time"] <= now for r in checks)
        have.append(t)
    print(f"{len(have)} tokens that passed the 13 checks, with price data\n")

    new_filters = lambda t: "High holder correlation" in t["warn"] or t["top10"] < 1 or t["v2l"] < 0.1

    def buys(cap, filters=True):
        out = []
        for t in have:
            if filters and new_filters(t): continue
            if cap is not None and t["v2l"] > cap: continue
            if t["sells"] > t["buys"] or t["copycat"] or not t["web"]: continue
            out.append(t)
        return out

    def score(lst, **kw):
        r = [usd(simulate(t["entry"], t["path"], **kw)[0]) for t in lst]
        return sum(r), (sum(x > 0 for x in r) / len(r) * 100 if r else 0)

    print("1. THE CODE JUDGE WITH THE VOLUME CAP AT DIFFERENT LEVELS (exits: 4h + late trail)")
    print(f"   {'volume cap':22} {'buys':>4} {'won':>5} {'hit+100%':>9} {'total':>9} {'per trade':>10}")
    for cap in (5, 10, 20, 40, None):
        lst = buys(cap)
        tot, win = score(lst)
        print(f"   {('max ' + str(cap) + 'x') if cap else 'OFF':22} {len(lst):>4} {win:>4.0f}% "
              f"{sum(t['max_pct'] >= 100 for t in lst):>9} {tot:>+9.2f} {tot / len(lst) if lst else 0:>+10.2f}")
    tot, win = score(have)
    print(f"   {'(buy every pass)':22} {len(have):>4} {win:>4.0f}% {sum(t['max_pct'] >= 100 for t in have):>9} {tot:>+9.2f} {tot / len(have):>+10.2f}")

    print("\n2. TIME STOP HOURS (late trail on), $ total")
    sets = {"cap OFF buys": buys(None), "cap 5x buys": buys(5), "every pass": have}
    print(f"   {'hours':>5} " + " ".join(f"{k:>16}" for k in sets))
    for h in (2, 3, 4, 5, 6, 8, 12):
        print(f"   {h:>5} " + " ".join(f"{score(v, tstop_h=h)[0]:>+16.2f}" for v in sets.values()))
    print(f"   {'6 old':>5} " + " ".join(f"{score(v, tstop_h=6, late_trail=None)[0]:>+16.2f}" for v in sets.values())
          + "   <- 6h without the late trail (the rules before today)")

    print("\n3. WHAT THE JUDGE BUYS WITH THE CAP OFF")
    for t in sorted(buys(None), key=lambda t: -t["v2l"]):
        r, why = simulate(t["entry"], t["path"])
        print(f"   {t['symbol'][:12]:12} v/l {t['v2l']:6.2f}  b/s {t['buys']}/{t['sells']}  max {t['max_pct']:+6.0f}%  {why:13} ${usd(r):+6.2f}")


if __name__ == "__main__":
    main()
