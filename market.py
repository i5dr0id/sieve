# market.py
# the pool itself: depth, age, price, and whether anyone can actually sell.
import time
import requests
from config import FACTS, TICKET_USD

DS = "https://api.dexscreener.com/tokens/v1/solana"


def pool(mint: str) -> dict | None:
    r = requests.get(f"{DS}/{mint}", timeout=15)
    r.raise_for_status()
    data = r.json()
    pairs = data if isinstance(data, list) else (data.get("pairs") or [])
    pairs = [p for p in pairs if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    h1 = (p.get("txns") or {}).get("h1") or {}
    born = p.get("pairCreatedAt")
    return {
        "symbol": (p.get("baseToken") or {}).get("symbol"),
        "price": float(p.get("priceUsd") or 0),
        "liq_usd": (p.get("liquidity") or {}).get("usd") or 0,
        "age_min": round((time.time() * 1000 - born) / 60000) if born else None,
        "buys_1h": h1.get("buys", 0),
        "sells_1h": h1.get("sells", 0),
        "vol_1h": (p.get("volume") or {}).get("h1"),
        "chg_1h": (p.get("priceChange") or {}).get("h1"),
        "websites": len((p.get("info") or {}).get("websites") or []),
        "socials": len((p.get("info") or {}).get("socials") or []),
        "url": p.get("url"),
    }


def market_kill(m: dict | None) -> str | None:
    if not m:                                                    return "no_pool"
    if m["price"] <= 0:                                          return "no_price"
    if m["liq_usd"] < FACTS["min_liquidity_usd"]:                return "thin_pool"
    if TICKET_USD / m["liq_usd"] > FACTS["max_ticket_share"]:    return "ticket_too_big"
    if m["age_min"] is None or m["age_min"] < FACTS["min_age_min"]:
        return "too_fresh"
    if m["age_min"] > FACTS["max_age_hours"] * 60:               return "too_old"
    if m["buys_1h"] >= 20 and m["sells_1h"] == 0:                return "nobody_can_sell"
    return None
