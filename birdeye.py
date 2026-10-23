# birdeye.py
# trend data the 13 checks can't see: holder and wallet growth, buy vs sell in USD (not just counts),
# price change across windows. free key, 60 calls/min shared. key lives in .env as BIRDEYE_API_KEY.
# logged and given to the AI shadow judge only. nothing here decides a trade until TODO.md #4 says so.
import os
import requests

URL = "https://public-api.birdeye.so/defi/token_overview"


def _key() -> str | None:
    if os.environ.get("BIRDEYE_API_KEY"):
        return os.environ["BIRDEYE_API_KEY"]
    if os.path.exists(".env"):
        for line in open(".env"):
            if line.startswith("BIRDEYE_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def trend(mint: str) -> dict | None:
    """Compact trend snapshot. None when there's no key or Birdeye has nothing."""
    key = _key()
    if not key:
        return None
    r = requests.get(URL, headers={"X-API-KEY": key, "x-chain": "solana"}, params={"address": mint}, timeout=15)
    r.raise_for_status()
    d = r.json().get("data") or {}
    if not d:
        return None
    pick = lambda *ks: {k: (round(d[k], 2) if isinstance(d.get(k), float) else d.get(k)) for k in ks}
    buy_usd, sell_usd = d.get("vBuy1hUSD") or 0, d.get("vSell1hUSD") or 0
    return {
        "holders": d.get("holder"),
        **pick("uniqueWallet5m", "uniqueWallet30m", "uniqueWallet1h", "uniqueWallet4h",
               "uniqueWallet1hChangePercent", "uniqueWallet4hChangePercent"),
        **pick("priceChange5mPercent", "priceChange30mPercent", "priceChange1hPercent",
               "priceChange4hPercent", "priceChange24hPercent"),
        **pick("buy1h", "sell1h", "buy4h", "sell4h"),
        "buy_usd_1h": round(buy_usd), "sell_usd_1h": round(sell_usd),
        "buy_share_usd_1h": round(buy_usd / (buy_usd + sell_usd), 3) if buy_usd + sell_usd else None,
        **pick("v1hUSD", "v24hUSD", "trade1h", "trade1hChangePercent", "numberMarkets"),
    }


if __name__ == "__main__":
    import json, sys
    print(json.dumps(trend(sys.argv[1]), indent=2))
