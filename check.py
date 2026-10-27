# check.py
# one contract address in, one verdict out. runs every time a token crosses your desk.
import csv, json, os, sys, time
from config import JUDGE, LOG, MIN_CONFIDENCE, PAPER, TICKET_USD
from rugcheck import report, fact_kill
from market import pool, market_kill
from grok import ask
from prompts import JUDGE_PROMPT
from fills import enter_both


def log(row: dict):
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["time", "mint", "symbol", "stage", "verdict",
                                          "confidence", "reason"])
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in w.fieldnames})


def check(mint: str) -> dict:
    try:
        token = report(mint)                                     # rug filter, free
    except Exception as e:
        return {"stage": "facts", "verdict": "SKIP", "reason": f"rugcheck failed: {e}"}
    if (k := fact_kill(token)):
        return {"stage": "facts", "verdict": "SKIP", "reason": k, "symbol": token["symbol"]}

    try:
        m = pool(mint)                                           # pool, free
    except Exception as e:
        return {"stage": "pool", "verdict": "SKIP", "reason": f"dexscreener failed: {e}"}
    if (k := market_kill(m)):
        return {"stage": "pool", "verdict": "SKIP", "reason": k, "symbol": token["symbol"]}

    if JUDGE != "grok":                                          # survivors wait for a human/Claude read
        return {"stage": "review", "verdict": "REVIEW", "symbol": m["symbol"] or token["symbol"],
                "reason": "passed 13 checks, needs X/narrative read", "price": m["price"],
                "liq_usd": m["liq_usd"], "url": m["url"], "token": token, "pool": m}

    try:
        ans = ask(JUDGE_PROMPT, {"token": token, "pool": m}, read_x=True)   # the only paid step
    except Exception as e:
        return {"stage": "grok", "verdict": "SKIP", "reason": f"grok failed: {e}"}

    verdict, conf = ans.get("verdict"), ans.get("confidence") or 0
    if verdict == "BUY" and conf < MIN_CONFIDENCE:
        verdict = "SKIP"
        ans["why"] = f"low confidence {conf}"
    return {**ans, "stage": "grok", "verdict": verdict, "symbol": m["symbol"] or token["symbol"],
            "reason": ans.get("why"), "price": m["price"], "liq_usd": m["liq_usd"], "url": m["url"]}


if __name__ == "__main__":
    mint = sys.argv[1].strip()
    v = check(mint)
    log({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, **v})
    if v["verdict"] == "BUY":
        v["action"] = " | ".join(enter_both(mint, v["symbol"], v["price"], v["liq_usd"]))
    print(json.dumps(v, indent=2))
