# tokenfacts.py
# research data, read-only. for every token that reached the judge, records two things the 13 checks don't see:
#   - how old its website's domain is: a site registered an hour before launch took an hour to make
#   - where its top 10 holders got their first SOL: a wallet factory (look-alike holders funded from one or two
#     tiny wallets) shows up as one funder behind several holders
# nothing here trades or changes a verdict. the Nov 5 review decides whether any of it becomes a rule.
#   python tokenfacts.py              tokens judged in the last 2 h, not yet recorded (run.sh runs this every cycle)
#   python tokenfacts.py --history    domain ages for every token ever judged. holders are skipped: they've moved on
import calendar, csv, fcntl, json, os, sys, time
from collections import Counter
from urllib.parse import urlparse
import requests
from config import DECISIONS
import rugcheck, wallets

OUT = "logs/paper/tokenfacts.csv"
COLS = ["checked", "mint", "symbol", "mode", "url", "host", "domain", "domain_created", "domain_age_days",
        "holders_traced", "busy", "fresh_7d", "tiny_funded", "biggest_cluster", "cluster_funder", "funders"]
FRESH_H = 2              # the engine only does tokens this recent: holders must be read near the decision
MAX_PAGES = 2            # a wallet with more than 2000 txs is an old, active wallet, not a fresh factory one
TINY_SOL = 0.1           # first deposit under this = funded with just enough for fees
# a site on one of these says nothing about effort through its domain's age: it's logged as host "free"
FREE_HOSTS = ("vercel.app", "netlify.app", "github.io", "pages.dev", "carrd.co", "linktr.ee", "x.com", "twitter.com",
              "t.me", "pump.fun", "framer.website", "framer.ai", "webflow.io", "wixsite.com", "notion.site", "gitbook.io",
              "replit.app", "lovable.app", "onrender.com", "glitch.me", "bolt.host", "base44.app", "netlify.com",
              "tiktok.com", "instagram.com", "youtube.com", "medium.com", "substack.com", "dexscreener.com")


def judged() -> dict:
    """first REVIEW per mint: the moment it passed the 13 checks and went to the judge."""
    first = {}
    for r in csv.DictReader(open(DECISIONS)):
        if r["verdict"] == "REVIEW" and r["mint"] not in first:
            first[r["mint"]] = r
    return first


def website(mint: str) -> str | None:
    r = requests.get(f"https://api.dexscreener.com/tokens/v1/solana/{mint}", timeout=15)
    r.raise_for_status()
    for p in r.json() or []:
        for w in (p.get("info") or {}).get("websites") or []:
            if w.get("url"):
                return w["url"]
    return None


def domain_age(url: str, checked: float) -> dict:
    host = (urlparse(url if "://" in url else "https://" + url).hostname or "").lower().removeprefix("www.")
    if not host:
        return {"host": "none"}
    if any(host == h or host.endswith("." + h) for h in FREE_HOSTS):
        return {"host": "free", "domain": host}
    parts = host.split(".")
    domain = ".".join(parts[-3:] if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "net", "org") else parts[-2:])
    out = {"host": "own", "domain": domain}
    try:
        r = requests.get(f"https://rdap.org/domain/{domain}", timeout=15)
        if r.status_code == 200:
            for ev in r.json().get("events") or []:
                if ev.get("eventAction") == "registration":
                    created = calendar.timegm(time.strptime(ev["eventDate"][:19], "%Y-%m-%dT%H:%M:%S"))   # RDAP dates are UTC
                    out.update(domain_created=ev["eventDate"][:19], domain_age_days=round((checked - created) / 86400, 2))
        else:
            out["domain_created"] = f"rdap {r.status_code}"
    except requests.RequestException as e:
        out["domain_created"] = f"rdap {type(e).__name__}"
    return out


def first_funding(owner: str) -> dict:
    """the wallet's oldest transaction, and who sent it SOL there."""
    sigs, before = [], None
    for _ in range(MAX_PAGES):
        page = wallets.rpc("getSignaturesForAddress", [owner, {"limit": 1000, **({"before": before} if before else {})}])
        sigs += page
        if len(page) < 1000:
            break
        before = page[-1]["signature"]
    else:
        return {"busy": True}
    if not sigs:
        return {}
    first = sigs[-1]
    tx = wallets.rpc("getTransaction", [first["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}]) or {}
    msg, meta = (tx.get("transaction") or {}).get("message") or {}, tx.get("meta") or {}
    keys = [k["pubkey"] for k in msg.get("accountKeys") or []]
    out = {"first": first.get("blockTime")}
    ixs = list(msg.get("instructions") or [])
    for inner in meta.get("innerInstructions") or []:
        ixs += inner.get("instructions") or []
    for ix in ixs:
        p = ix.get("parsed")
        if isinstance(p, dict) and p.get("type") in ("transfer", "createAccount", "transferWithSeed"):
            info = p.get("info") or {}
            if owner in (info.get("destination"), info.get("newAccount")) and info.get("lamports"):
                return {**out, "funder": info.get("source"), "sol": info["lamports"] / 1e9}
    # no plain transfer (wrapped SOL unwrapped into it, a relayer...): whoever signed and paid for the tx funded it
    if owner in keys and keys[0] != owner:
        i = keys.index(owner)
        got = (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9 if meta.get("postBalances") else 0
        if got > 0:
            return {**out, "funder": keys[0], "sol": got}
    return out


def holders(mint: str, checked: float) -> dict:
    owners = [h["owner"] for h in rugcheck._holders(rugcheck._get(mint))[:10] if h.get("owner")]
    traced = {}
    for o in owners:
        try:
            traced[o] = first_funding(o)
        except Exception:
            continue
        time.sleep(0.15)
    funders = Counter(f["funder"] for f in traced.values() if f.get("funder"))
    top = funders.most_common(1)
    return {"holders_traced": len(traced),
            "busy": sum(1 for f in traced.values() if f.get("busy")),
            "fresh_7d": sum(1 for f in traced.values() if f.get("first") and checked - f["first"] < 7 * 86400),
            "tiny_funded": sum(1 for f in traced.values() if f.get("funder") and f["sol"] < TINY_SOL),
            "biggest_cluster": top[0][1] if top else 0, "cluster_funder": top[0][0] if top else "",
            "funders": json.dumps({o[:6]: (f.get("funder") or "")[:6] for o, f in traced.items()})}


def main(history: bool):
    done = {r["mint"] for r in csv.DictReader(open(OUT))} if os.path.exists(OUT) else set()
    todo = []
    for mint, r in judged().items():
        checked = time.mktime(time.strptime(r["time"][:16], "%Y-%m-%d %H:%M"))
        if mint not in done and (history or time.time() - checked < FRESH_H * 3600):
            todo.append((mint, r, checked))
    for mint, r, checked in todo:
        row = {"checked": r["time"], "mint": mint, "symbol": r["symbol"], "mode": "history" if history else "live"}
        try:
            row["url"] = website(mint) or ""
            if row["url"]:
                row.update(domain_age(row["url"], checked))
            else:
                row["host"] = "none"
            if not history:
                row.update(holders(mint, checked))
        except Exception as e:
            print(f"tokenfacts {r['symbol']}: {type(e).__name__}, retry next cycle")
            continue
        new = not os.path.exists(OUT)
        with open(OUT, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            if new:
                w.writeheader()
            w.writerow(row)
        time.sleep(1)


if __name__ == "__main__":
    lock = open("logs/paper/.tokenfacts.lock", "w")
    try:                                     # the engine starts this in the background every cycle: one at a time
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(0)
    main("--history" in sys.argv)
