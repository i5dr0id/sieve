# scan.py
# lead sources: DexScreener's latest profiles, latest boosts and top boosts, and GeckoTerminal's trending pools
# (Solana only). a paid profile or boost is not a quality signal, it just means someone spent money. the
# trending pools catch tokens that never paid DexScreener for anything. the filter decides either way.
import csv, os, subprocess, sys, time
from datetime import datetime
import requests
from config import DECISIONS, FACTS, LOG

FEEDS = ["token-boosts/top/v1", "token-boosts/latest/v1", "token-profiles/latest/v1"]
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools"
GECKO_PAGES = [("1h", 1), ("1h", 2), ("6h", 1)]   # 20 pools a page. free API: ~30 calls a minute, so keep this short
QUOTES = {"So11111111111111111111111111111111111111112",   # SOL, USDC, USDT: the other side of a pool, never a lead
          "EPjFWdd5AaufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY5NX6ytsJDy6pnB"}
PER_RUN = 8                              # cap per run, so one busy hour can't flood the desk
SOURCES = os.path.join(os.path.dirname(DECISIONS), "sources.csv")   # which source found each token, for the backtests

# a token skipped because a source was down was never really checked, so it stays eligible.
# logs/live/checks.csv is the history from before the dual-mode engine (2026-10-27): those count as seen too
seen = {r["mint"] for f in (LOG, "logs/live/checks.csv") if os.path.exists(f)
        for r in csv.DictReader(open(f)) if "failed:" not in (r["reason"] or "")}

# rugcheck is the first network stage. if it's down, every token would die unchecked: skip the whole run
try:
    requests.get("https://api.rugcheck.xyz/", timeout=10)    # any answer counts as up, only no connection is down
except Exception as e:
    print(f"rugcheck down, scan skipped this run: {type(e).__name__}", file=sys.stderr)
    sys.exit(0)
fresh = {}                               # mint -> the sources that listed it, in the order found
for feed in FEEDS:
    try:
        r = requests.get(f"https://api.dexscreener.com/{feed}", timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"ERROR feed {feed} down: {e}", file=sys.stderr)
        continue
    for t in r.json():
        mint = t.get("tokenAddress")
        if t.get("chainId") == "solana" and mint not in seen and "dexscreener" not in fresh.get(mint, []):
            fresh.setdefault(mint, []).append("dexscreener")

# trending pools come with their liquidity and age, so the ones the pool check would kill are left out here
# for free. too young is not seen: it comes back next run if it is still trending.
for duration, page in GECKO_PAGES:
    try:
        r = requests.get(GECKO, params={"duration": duration, "page": page}, timeout=15,
                         headers={"accept": "application/json"})
        r.raise_for_status()
    except Exception as e:                # a 429 here only means fewer leads this run
        print(f"ERROR feed geckoterminal trending {duration} down: {type(e).__name__}", file=sys.stderr)
        break
    for p in r.json().get("data", []):
        a = p["attributes"]
        mint = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
        age_min = (time.time() - datetime.fromisoformat(a["pool_created_at"].replace("Z", "+00:00")).timestamp()) / 60
        if (mint in seen or mint in QUOTES or float(a.get("reserve_in_usd") or 0) < FACTS["min_liquidity_usd"]
                or not FACTS["min_age_min"] <= age_min <= FACTS["max_age_hours"] * 60):
            continue
        if "geckoterminal" not in fresh.get(mint, []):
            fresh.setdefault(mint, []).append("geckoterminal")
    time.sleep(2)

new = not os.path.exists(SOURCES)
with open(SOURCES, "a", newline="") as f:
    w = csv.writer(f)
    if new:
        w.writerow(["time", "mint", "source"])
    for mint in list(fresh)[:PER_RUN]:
        w.writerow([time.strftime("%Y-%m-%d %H:%M"), mint, "+".join(fresh[mint])])
        f.flush()
        subprocess.run([sys.executable, "check.py", mint])
