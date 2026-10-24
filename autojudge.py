# autojudge.py
# the code judge. any REVIEW that has waited CODE_JUDGE_AFTER_MIN with no human/Claude/Grok verdict
# gets judged here by plain rules, so the desk keeps working when nobody is watching.
# the rules are the warning signs that killed every first-hour-pump survivor on 2026-10-18/19.
import csv, os, subprocess, sys, time
from config import LOG, CODE_JUDGE, CODE_JUDGE_AFTER_MIN
from market import pool

JUDGES = ("claude", "grok", "code")


def rules(m: dict, symbol: str, mint: str, checks: list[dict]) -> str | None:
    """First broken rule wins. None = BUY."""
    r = CODE_JUDGE
    if r["max_chg_1h_pct"] is not None and (m.get("chg_1h") or 0) > r["max_chg_1h_pct"]:
        return f"up {m['chg_1h']:.0f}% in the last hour (max {r['max_chg_1h_pct']})"
    if m["liq_usd"] and (m.get("vol_1h") or 0) / m["liq_usd"] > r["max_vol_to_liq_1h"]:
        return f"1h volume {m['vol_1h'] / m['liq_usd']:.1f}x the pool (max {r['max_vol_to_liq_1h']})"
    if m["liq_usd"] and (m.get("vol_1h") or 0) / m["liq_usd"] < r["min_vol_to_liq_1h"]:
        return f"fake climb: 1h volume {(m.get('vol_1h') or 0) / m['liq_usd']:.2f}x the pool (min {r['min_vol_to_liq_1h']})"
    if r["sells_over_buys_1h"] and m["sells_1h"] > m["buys_1h"]:
        return f"sellers in control: {m['sells_1h']} sells vs {m['buys_1h']} buys in 1h"
    cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - r["copycat_hours"] * 3600))
    twins = {c["mint"] for c in checks if (c["symbol"] or "").lower() == (symbol or "").lower()
             and c["mint"] != mint and c["time"] >= cutoff}
    if twins:
        return f"copycat risk: {len(twins)} other '{symbol}' contract(s) in {r['copycat_hours']}h"
    if r["require_website"] and not m.get("websites"):
        return "no website"
    return None


def main():
    if CODE_JUDGE_AFTER_MIN is None or not os.path.exists(LOG):
        return
    checks = list(csv.DictReader(open(LOG)))
    judged = {c["mint"] for c in checks if c["stage"] in JUDGES}
    cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - CODE_JUDGE_AFTER_MIN * 60))
    waiting = {c["mint"]: c for c in checks if c["verdict"] == "REVIEW" and c["mint"] not in judged
               and c["time"] <= cutoff}
    for mint, c in waiting.items():
        try:
            m = pool(mint)
        except Exception as e:
            print(f"ERROR code judge: dexscreener down for {c['symbol']} ({type(e).__name__}), retry next run")
            continue
        if not m:
            args = ["SKIP", "0.9", "pool gone before the code judge ran"]
        elif (why := rules(m, c["symbol"], mint, checks)):
            args = ["SKIP", "0.8", f"[code] {why}"]
        else:
            args = ["BUY", str(CODE_JUDGE["confidence"]), "[code] passed every code-judge rule"]
        out = subprocess.run([sys.executable, "verdict.py", mint, *args, "code"],
                             capture_output=True, text=True)
        print(f"CODE JUDGE {(out.stdout or out.stderr).strip()}")


if __name__ == "__main__":
    main()
