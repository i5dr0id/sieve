# rugcheck.py
# one report per token, trimmed to the fields the desk reads. Grok never sees the raw report.
import requests
from config import FACTS, RUGCHECK_KEY

RC = "https://api.rugcheck.xyz/v1/tokens"


def _get(mint: str) -> dict:
    r = requests.get(f"{RC}/{mint}/report", timeout=20, headers={"X-API-KEY": RUGCHECK_KEY} if RUGCHECK_KEY else {})
    r.raise_for_status()
    return r.json()


def _holders(d: dict) -> list[dict]:
    """top holders minus the AMM vaults and lockers: they sit in the list, but they are not whales."""
    known = d.get("knownAccounts") or {}

    def is_pool(h):
        tag = known.get(h.get("owner")) or known.get(h.get("address")) or {}
        return str(tag.get("type", "")).upper() in ("AMM", "LOCKER")

    return [h for h in (d.get("topHolders") or []) if not is_pool(h)]


def wallets(mint: str) -> dict:
    """who to watch after a buy (wallets.py): the creator wallet, and the top 10 holders' token accounts."""
    d = _get(mint)
    return {"creator": d.get("creator"), "top10": [h["address"] for h in _holders(d)[:10] if h.get("address")]}


def report(mint: str) -> dict:
    d = _get(mint)
    token = d.get("token") or {}
    holders = _holders(d)
    markets = sorted(d.get("markets") or [],
                     key=lambda m: ((m.get("lp") or {}).get("baseUSD") or 0)
                                 + ((m.get("lp") or {}).get("quoteUSD") or 0),
                     reverse=True)
    lp = (markets[0].get("lp") or {}) if markets else {}
    supply = token.get("supply") or 0
    risks = d.get("risks") or []

    return {
        "mint": mint,
        "symbol": (d.get("tokenMeta") or {}).get("symbol"),
        "rugged": bool(d.get("rugged")),
        "risk_score": d.get("score_normalised"),
        "danger": [x.get("name") for x in risks if x.get("level") == "danger"],
        "warn": [x.get("name") for x in risks if x.get("level") == "warn"],
        "mint_authority": token.get("mintAuthority", d.get("mintAuthority")),
        "freeze_authority": token.get("freezeAuthority", d.get("freezeAuthority")),
        "lp_locked_pct": lp.get("lpLockedPct", d.get("lpLockedPct")),
        "top10_pct": round(sum(h.get("pct") or 0 for h in holders[:10]), 2) if holders else None,
        "dev_pct": round((d.get("creatorBalance") or 0) / supply * 100, 2) if supply else None,
        "insiders": sum(1 for h in holders if h.get("insider")) + (d.get("graphInsidersDetected") or 0),
        "holders": d.get("totalHolders"),
    }


def fact_kill(t: dict) -> str | None:
    """Plain comparisons. First failure wins, the reason gets logged."""
    if t["risk_score"] is None:                                  return "no_report"
    if t["rugged"]:                                              return "already_rugged"
    if t["mint_authority"]:                                      return "mint_open"
    if t["freeze_authority"]:                                    return "freeze_open"
    if t["danger"]:                                              return "danger:" + t["danger"][0]
    if (w := [x for x in t["warn"] if x in FACTS["kill_warns"]]): return "warn:" + w[0]
    if t["risk_score"] > FACTS["max_risk_score"]:                return "risk_score"
    if t["lp_locked_pct"] is None or t["lp_locked_pct"] < FACTS["min_lp_locked_pct"]:
        return "lp_unlocked"
    if t["top10_pct"] is None or t["top10_pct"] > FACTS["max_top10_pct"]:
        return "top10_heavy"
    if t["top10_pct"] < FACTS["min_top10_pct"]:                  return "top10_too_flat"
    if t["dev_pct"] is None or t["dev_pct"] > FACTS["max_dev_pct"]:
        return "dev_holds"
    if t["insiders"] > FACTS["max_insiders"]:                    return "insiders"
    return None
