# shadowjudge.py
# an AI judge that only WATCHES. every token that passes the 13 checks gets an AI verdict,
# written to logs/<mode>/shadow.csv and followed up at +6h / +24h like the real judge's calls.
# it never buys, never sells, and never writes to checks.csv (trade.py's approval check reads that file).
#   python shadowjudge.py          judge any recent REVIEW it hasn't seen (run.sh calls it every loop)
# the model runs headless with every tool switched off (--tools ""): it can only answer in text.
import csv, json, os, re, subprocess, time
from config import LOG, SHADOW, SHADOW_JUDGE
from market import pool
from rugcheck import report
import birdeye
import followup

FIELDS = ["time", "mint", "symbol", "model", "verdict", "confidence", "why", "main_risk", "price0", "secs", "trend"]
WORKDIR = "logs/shadow_ws"           # empty folder: nothing for the model to look at even if it tried
MAX_AGE_MIN = 30                     # only judge fresh reviews, so the verdict is on the same data the rules saw
PER_RUN = 3

PROMPT = """You are the judge on a Solana memecoin desk. This token just passed 13 hard checks in code:
mint/freeze authority, LP locked, holder concentration, dev wallet, insiders, pool depth, age.
Do not re-check those numbers. Decide if ONE flat $5 ticket goes in. You never size, never pick exits.
Exits are fixed: stop -35%, sell half at +100%, a quarter at +200%, 30% trailing stop, 6h time stop.

Judge what the numbers suggest together: is this organic demand or bot churn / a pump about to dump?
Look at buys vs sells, volume vs pool, price change, age, holders, websites/socials, the warn-level risks.
"trend" (Birdeye, may be null) adds wallet growth, buy vs sell in USD, and price change across windows.
Many tiny buys with sell-side USD volume as large is bot churn, not demand.
You have no internet access; judge only from the data below.

DATA:
{data}

Reply with ONLY this JSON, nothing else:
{{"verdict": "BUY" or "SKIP", "confidence": 0.0-1.0, "why": "max two short sentences", "main_risk": "one short line"}}
NEVER answer BUY when a field you needed is null."""


def _rows() -> list[dict]:
    return list(csv.DictReader(open(SHADOW))) if os.path.exists(SHADOW) else []


def _append(row: dict):
    new = not os.path.exists(SHADOW)
    with open(SHADOW, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def ask(data: dict) -> dict:
    os.makedirs(WORKDIR, exist_ok=True)
    cmd = ["claude", "-p", "--model", SHADOW_JUDGE["model"], "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", PROMPT.format(data=json.dumps(data, default=str))]
    r = subprocess.run(cmd, cwd=WORKDIR, capture_output=True, text=True,
                       timeout=SHADOW_JUDGE["timeout_s"], stdin=subprocess.DEVNULL)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if r.returncode != 0 or not m:
        raise RuntimeError(f"no JSON from model (rc {r.returncode}): {(r.stdout or r.stderr)[-160:]!r}")
    ans = json.loads(m.group(0))
    if ans.get("verdict") not in ("BUY", "SKIP"):
        raise RuntimeError(f"bad verdict {ans.get('verdict')!r}")
    return ans


def main():
    if not SHADOW_JUDGE or not os.path.exists(LOG):
        return
    done = {r["mint"] for r in _rows()}
    cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - MAX_AGE_MIN * 60))
    todo = {}
    for c in csv.DictReader(open(LOG)):
        if c["verdict"] == "REVIEW" and c["mint"] not in done and c["time"] >= cutoff:
            todo[c["mint"]] = c
    for mint, c in list(todo.items())[:PER_RUN]:
        t0 = time.time()
        try:
            m = pool(mint)
            if not m:
                continue
            try:
                tr = birdeye.trend(mint)
            except Exception:
                tr = None                                # Birdeye down: judge without it
            ans = ask({"token": report(mint), "pool": m, "trend": tr})
        except Exception as e:
            print(f"SHADOW ERROR {c['symbol']}: {type(e).__name__}: {str(e)[:160]}")
            continue
        _append({"time": time.strftime("%Y-%m-%d %H:%M"), "mint": mint, "symbol": c["symbol"],
                 "model": SHADOW_JUDGE["model"], "verdict": ans["verdict"], "confidence": ans.get("confidence"),
                 "why": ans.get("why"), "main_risk": ans.get("main_risk"), "price0": m["price"],
                 "secs": round(time.time() - t0), "trend": json.dumps(tr) if tr else ""})
        followup.start(mint, c["symbol"], "ai-shadow", ans["verdict"], m)
        print(f"SHADOW {ans['verdict']} {c['symbol']} ({ans.get('confidence')}): {ans.get('why')}")


if __name__ == "__main__":
    main()
