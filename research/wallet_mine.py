# read-only: mine early buyers across winning tokens, find overlap, deep-vet leads. no trading.
import sys, time, csv, json, collections, statistics, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests, config

S = os.path.dirname(os.path.abspath(__file__))
KEY, RPC, API = config.ENV["HELIUS_API_KEY"], config.RPC_URLS[0], "https://api.helius.xyz/v0"
WSOL = "So11111111111111111111111111111111111111112"
MIN_ENTRY_SOL = 0.05          # below this = volume bot dust
calls = 0
short = lambda a: a[:4] + "…" + a[-4:]

def _get(url, **kw):
    global calls; calls += 1; time.sleep(0.12)
    r = requests.get(url, timeout=60, **kw); r.raise_for_status(); return r.json()
def _post(url, **kw):
    global calls; calls += 1; time.sleep(0.12)
    r = requests.post(url, timeout=60, **kw); r.raise_for_status(); return r.json()
def rpc(m, p): return _post(RPC, json={"jsonrpc": "2.0", "id": 1, "method": m, "params": p})["result"]

def flows(tx, w):
    sol = sum(a.get("nativeBalanceChange", 0) for a in tx.get("accountData", []) if a.get("account") == w) / 1e9
    tok = collections.Counter()
    for t in tx.get("tokenTransfers", []):
        amt = t.get("tokenAmount") or 0
        if t.get("mint") == WSOL:
            sol += amt if t.get("toUserAccount") == w else 0
            sol -= amt if t.get("fromUserAccount") == w else 0
            continue
        if t.get("toUserAccount") == w: tok[t["mint"]] += amt
        if t.get("fromUserAccount") == w: tok[t["mint"]] -= amt
    return sol, tok

def early_buyers(mint):
    before, sigs = None, []
    for _ in range(60):
        p = {"limit": 1000, **({"before": before} if before else {})}
        page = rpc("getSignaturesForAddress", [mint, p]); sigs += page
        if len(page) < 1000: break
        before = page[-1]["signature"]
    oldest = [s["signature"] for s in reversed(sigs) if not s.get("err")][:200]
    txs = []
    for i in range(0, len(oldest), 100):
        txs += _post(f"{API}/transactions", params={"api-key": KEY}, json={"transactions": oldest[i:i+100]})
    txs.sort(key=lambda t: (t.get("slot", 0), t.get("timestamp", 0)))
    dep, slot0 = txs[0].get("feePayer"), txs[0].get("slot")
    out = {}
    for t in txs:
        w = t.get("feePayer"); sol, tok = flows(t, w)
        if tok.get(mint, 0) > 0 and sol < 0 and w not in out and w != dep and t["slot"] - slot0 > 2 and -sol >= MIN_ENTRY_SOL:
            out[w] = round(-sol, 3)
    return len(sigs), len(sigs) >= 60000, dep, out

def vet(w, pages=10, want=30):
    per = collections.defaultdict(lambda: {"in": 0.0, "out": 0.0, "t_buy": None, "t_sell": None})
    before, n = None, 0
    for _ in range(pages):
        h = _get(f"{API}/addresses/{w}/transactions", params={"api-key": KEY, "type": "SWAP", "limit": 100, **({"before": before} if before else {})})
        if not h: break
        for tx in h:
            n += 1; sol, tok = flows(tx, w); ts = tx.get("timestamp")
            for m, amt in tok.items():
                d = per[m]
                if sol < 0 and amt > 0: d["in"] += -sol; d["t_buy"] = min(filter(None, [d["t_buy"], ts]))
                if sol > 0 and amt < 0: d["out"] += sol; d["t_sell"] = max(filter(None, [d["t_sell"], ts]))
        before = h[-1]["signature"]
        if sum(1 for d in per.values() if d["out"] > 0 and d["in"] > 0) >= want or len(h) < 100: break
    closed = {m: d for m, d in per.items() if d["out"] > 0 and d["in"] > 0}
    won = sum(1 for d in closed.values() if d["out"] > d["in"])
    profits = sorted((d["out"] - d["in"] for d in closed.values()), reverse=True)
    real = sum(profits)
    holds = [(d["t_sell"] - d["t_buy"]) / 60 for d in closed.values() if d["t_buy"] and d["t_sell"] and d["t_sell"] > d["t_buy"]]
    top_share = profits[0] / real * 100 if real > 0 and profits else None
    sizes = [d["in"] for d in closed.values()]
    return {"swaps": n, "tokens": len(per), "closed": len(closed), "won": won,
            "win_pct": round(won / len(closed) * 100) if closed else 0, "realized_sol": round(real, 3),
            "top_token_share_pct": round(top_share) if top_share else None,
            "median_hold_min": round(statistics.median(holds)) if holds else None,
            "median_size_sol": round(statistics.median(sizes), 3) if sizes else None}

def verdict(v):
    if v["closed"] < 30: return f"not enough history ({v['closed']} closed)"
    if v["win_pct"] > 90: return "win% suspiciously high"
    if v["realized_sol"] <= 0: return "loses money"
    if v["top_token_share_pct"] and v["top_token_share_pct"] > 60: return "one lucky token"
    if v["median_hold_min"] is not None and v["median_hold_min"] < 2: return "too fast to copy (bot)"
    if v["win_pct"] < 50: return "win% too low"
    return "PASSES"

try:
    rows = list(csv.DictReader(open(f"{S}/followups.csv")))
    win = {}
    for r in rows:
        p24, p6 = r.get("pct_24h"), r.get("pct_6h")
        if (p24 and float(p24) >= 20) or (not p24 and p6 and float(p6) >= 50):
            win[r["mint"]] = (r["symbol"], p24 or f"{p6} (6h)")
    win.setdefault("2qPoPQQCHGtDbgdSxXfrzW1iRS3cGbKmMWSMapZ4pump", ("DOAS", "+48 (open)"))
    win = dict(list(win.items())[:6])

    seen = collections.defaultdict(list)
    print("=== real early buyers per winning token (excl. deployer, snipers, dust bots) ===")
    for mint, (sym, pct) in win.items():
        n, capped, dep, buyers = early_buyers(mint)
        print(f"{sym:<10} {pct:>12}%  txns {n}{'+' if capped else ''}  deployer {short(dep)}  real early buyers: {len(buyers)}")
        for w, s in buyers.items(): seen[w].append((sym, s))
    multi = {w: v for w, v in seen.items() if len(v) >= 2}
    print(f"\nwallets early in 2+ winners: {len(multi)}")
    for w, v in multi.items(): print(f"  {short(w)}: " + ", ".join(f"{s} ({x} SOL)" for s, x in v))

    # deep-vet: overlap wallets first, then biggest early entries; cap 8
    ranked = list(multi) + [w for w, v in sorted(seen.items(), key=lambda kv: -max(x for _, x in kv[1])) if w not in multi]
    print(f"\n=== deep vet (up to 1000 swaps each, stop at 30 closed) ===")
    print(f"{'wallet':<11} {'in':>3} {'closed':>6} {'win%':>5} {'realized':>9} {'top1%':>6} {'hold':>6} {'size':>6}  verdict")
    res = {}
    for w in ranked[:8]:
        v = vet(w); res[w] = {**v, "winners": seen[w]}
        print(f"{short(w):<11} {len(seen[w]):>3} {v['closed']:>6} {v['win_pct']:>4}% {v['realized_sol']:>+8.2f}S "
              f"{(str(v['top_token_share_pct'])+'%') if v['top_token_share_pct'] is not None else '-':>6} "
              f"{(str(v['median_hold_min'])+'m') if v['median_hold_min'] is not None else '-':>6} {v['median_size_sol'] or 0:>6}  {verdict(v)}")
    json.dump(res, open(f"{S}/wallet_vet.json", "w"), indent=1)
    print(f"\nHelius calls used: {calls}   (full addresses saved to scratchpad/wallet_vet.json)")
except Exception as e:
    print("ERROR:", config.scrub(e)); print("calls so far:", calls)
