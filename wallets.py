# wallets.py
# a rug shows in the wallets before it shows on the chart. at the first exit check after a buy, snapshot() records
# the creator wallet's balance and the top 10 holders' token accounts. tripwire() compares every later check against
# it: the dev selling, or the top 10 quietly getting lighter, can fire before the price does.
# read-only: one Rugcheck report per position, then two RPC reads per check. it never signs anything.
import time
import requests
from config import RPC_URLS, WALLET_WATCH, scrub
from rugcheck import wallets


def rpc(method: str, params: list):
    """read-only twin of trade.rpc: tries each endpoint in order. errors never carry the URL (the key is in it)."""
    err = f"rpc {method}: no endpoint"
    for url in RPC_URLS:
        try:
            r = requests.post(url, timeout=15, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except requests.RequestException as e:
            err = f"rpc {method}: {type(e).__name__}"
            continue
        if r.status_code != 200:
            err = f"rpc {method}: HTTP {r.status_code}"
            continue
        d = r.json()
        if "error" in d:
            err = scrub(f"rpc {method}: {d['error']}")
            continue
        return d["result"]
    raise RuntimeError(err)


def _ui(acc: dict) -> float:
    try:
        return float(acc["data"]["parsed"]["info"]["tokenAmount"]["uiAmount"] or 0)
    except (KeyError, TypeError):                # closed and reused as something else: none of this token left
        return 0.0


def dev_balance(owner: str, mint: str) -> float:
    """every token account the creator holds for this mint, summed."""
    res = rpc("getTokenAccountsByOwner", [owner, {"mint": mint}, {"encoding": "jsonParsed"}])
    return sum(_ui(a["account"]) for a in res["value"])


def balances(accounts: list[str]) -> dict[str, float]:
    """one call for all ten. a closed account comes back null, and null means emptied."""
    res = rpc("getMultipleAccounts", [accounts, {"encoding": "jsonParsed"}])
    return {a: (_ui(acc) if acc else 0.0) for a, acc in zip(accounts, res["value"])}


def snapshot(mint: str) -> dict:
    """the wallets right after the buy. a holder already at zero is left out: there is nothing left to sell."""
    w = wallets(mint)
    supply = float(rpc("getTokenSupply", [mint])["value"]["uiAmount"] or 0)
    dev0 = dev_balance(w["creator"], mint) if w["creator"] else 0.0
    holders0 = {a: v for a, v in balances(w["top10"]).items() if v > 0} if w["top10"] else {}
    return {"creator": w["creator"], "dev0": dev0, "dev0_pct": round(dev0 / supply * 100, 3) if supply else 0,
            "holders0": holders0, "at": time.time()}


def tripwire(mint: str, snap: dict) -> str | None:
    """the first wallet rule that fires, as "rule (detail)", or None. a failed read raises: the caller holds."""
    W = WALLET_WATCH
    if snap["creator"] and snap["dev0"] > 0 and snap["dev0_pct"] >= W["dev_arm_pct"]:
        drop = (1 - dev_balance(snap["creator"], mint) / snap["dev0"]) * 100
        if drop >= W["dev_sell_pct"]:
            return f"dev_sold (creator wallet -{drop:.0f}%)"
    if snap["holders0"]:
        now = balances(list(snap["holders0"]))
        before, after = sum(snap["holders0"].values()), sum(now.values())
        gone = sum(1 for a in snap["holders0"] if now.get(a, 0) == 0)
        peel = (1 - after / before) * 100 if before else 0
        if peel >= W["holders_peel_pct"] or gone >= W["holders_gone"]:
            return f"holders_exit (top 10 -{peel:.0f}%, {gone} emptied)"
    return None
