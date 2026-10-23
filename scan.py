# scan.py
# lead sources: DexScreener's latest profiles, latest boosts and top boosts (Solana only).
# a paid profile or boost is not a quality signal, it just means someone spent money. the filter decides.
import csv, os, subprocess, sys
import requests
from config import LOG

FEEDS = ["token-boosts/top/v1", "token-boosts/latest/v1", "token-profiles/latest/v1"]
PER_RUN = 8                              # cap per run, so one busy hour can't flood the desk

# a token skipped because a source was down was never really checked, so it stays eligible
seen = ({r["mint"] for r in csv.DictReader(open(LOG)) if "failed:" not in (r["reason"] or "")}
        if os.path.exists(LOG) else set())

# rugcheck is the first network stage. if it's down, every token would die unchecked: skip the whole run
try:
    requests.get("https://api.rugcheck.xyz/", timeout=10)    # any answer counts as up, only no connection is down
except Exception as e:
    print(f"rugcheck down, scan skipped this run: {type(e).__name__}", file=sys.stderr)
    sys.exit(0)
fresh = []
for feed in FEEDS:
    try:
        r = requests.get(f"https://api.dexscreener.com/{feed}", timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"ERROR feed {feed} down: {e}", file=sys.stderr)
        continue
    for t in r.json():
        mint = t.get("tokenAddress")
        if t.get("chainId") == "solana" and mint not in seen and mint not in fresh:
            fresh.append(mint)

for mint in fresh[:PER_RUN]:
    subprocess.run([sys.executable, "check.py", mint])
