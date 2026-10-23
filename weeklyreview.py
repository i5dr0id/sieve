# weeklyreview.py
# the "CEO" seat: once a week, gather the week's numbers and have an AI argue AGAINST the current setup.
# it reads nothing itself (no tools): this script hands it the numbers. it changes nothing: you decide.
#   python weeklyreview.py [days]     default 7. writes logs/<mode>/WEEKLY_REVIEW.md (+ a dated copy)
# run.sh calls it every Monday just after midnight.
import csv, json, os, re, statistics, subprocess, sys, time
from collections import Counter, defaultdict
import config
from config import LOG, TRADES, FOLLOWUPS, SHADOW, MODE

MODEL = "sonnet"                 # one call a week, so the stronger model is worth it
OUT = f"logs/{MODE}/WEEKLY_REVIEW.md"

PROMPT = """You are the CEO seat on a small automated Solana memecoin desk. Your job is to DISAGREE.
Do not be agreeable. Challenge the current setup using only the numbers below. Never invent numbers.
If the sample is too small to conclude something, say so plainly and say how much more data is needed.

How the desk works: tokens from DexScreener feeds -> 13 hard checks (rugcheck facts + pool) -> a code judge
(fixed rules) decides BUY/SKIP -> flat $5 tickets, exits fixed in code. An AI "shadow" judge also gives a
verdict on every survivor but never trades. Follow-ups record price +6h and +24h after every verdict.

CURRENT CONFIG:
{config}

THIS WEEK'S NUMBERS:
{stats}

Write markdown with exactly these sections, short, tables where useful:
## Verdict
GO (keep as is), HOLD (keep, but watch something specific) or KILL (stop live trading). One line why.
## What the numbers say
3-6 bullets. Each cites a number from above.
## The rule I'd challenge
The single setting most likely costing money or skipping winners, with the evidence.
## Code judge vs AI shadow judge
Who was right more often when they disagreed. Say if the sample is too small.
## One experiment for next week
One change, in paper or shadow first if it touches buying. A pass/fail number decided in advance.
## What I can't tell yet
Bullets."""


def rows(path) -> list[dict]:
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []


def avg(xs):
    return round(statistics.mean(xs), 1) if xs else None


def stats(days: int) -> dict:
    since = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - days * 86400))
    checks = [r for r in rows(LOG) if r["time"] >= since]
    trades = [r for r in rows(TRADES) if r["time"] >= since]
    fu = [r for r in rows(FOLLOWUPS) if r["decided"] >= since]
    shadow = {r["mint"]: r for r in rows(SHADOW) if r["time"] >= since}

    kills = Counter(f"{r['stage']}: {r['reason']}" for r in checks
                    if r["stage"] in ("facts", "pool", "limits") and "failed:" not in (r["reason"] or ""))
    closed = [t for t in trades if t["action"] in ("close", "partial")]
    by_judge = defaultdict(list)
    for r in fu:
        by_judge[f"{r['judge']} {r['verdict']}"].append(r)
    outcome = {k: {"n": len(v), "avg_pct_6h": avg([float(r["pct_6h"]) for r in v if r.get("pct_6h")]),
                   "avg_pct_24h": avg([float(r["pct_24h"]) for r in v if r.get("pct_24h")]),
                   "up_24h": sum(1 for r in v if r.get("pct_24h") and float(r["pct_24h"]) > 0)}
               for k, v in by_judge.items()}

    # head to head: same token, code judge vs AI shadow
    code = {r["mint"]: r for r in fu if r["judge"] in ("code", "claude", "grok")}
    disagree = []
    for mint, s in shadow.items():
        c = code.get(mint)
        if c and c["verdict"] != s["verdict"]:
            disagree.append({"symbol": s["symbol"], "code": c["verdict"], "ai": s["verdict"],
                             "pct_6h": c.get("pct_6h") or None, "pct_24h": c.get("pct_24h") or None})
    agree = sum(1 for m, s in shadow.items() if m in code and code[m]["verdict"] == s["verdict"])

    slips = [float(t["slippage_pct"]) for t in trades if t.get("slippage_pct")]
    return {
        "days": days, "mode": MODE,
        "tokens_checked": len({r["mint"] for r in checks}),
        "passed_13_checks": sum(1 for r in checks if r["verdict"] == "REVIEW"),
        "top_kill_reasons": kills.most_common(8),
        "trades_opened": sum(1 for t in trades if t["action"] == "open"),
        "exits": Counter(t["reason"] for t in closed).most_common(),
        "realized_pnl_usd": round(sum(float(t["pnl"]) for t in trades), 2),
        "green_exits": f"{sum(1 for t in closed if float(t['pnl']) > 0)}/{len(closed)}",
        "avg_slippage_pct": avg(slips),
        "verdict_outcomes": outcome,
        "shadow_vs_code": {"shadow_verdicts_logged": len(shadow),
                           "shadow_judge_running_since": (rows(SHADOW) or [{}])[0].get("time") or "2026-10-20 22:59 (no verdicts yet)",
                           "agreed": agree, "disagreed": len(disagree), "disagreements": disagree[:15]},
        "note": "tokens killed by the 13 checks get no follow-ups; backtest.py measures those separately.",
    }


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    s = stats(days)
    cfg = {"TICKET_USD": config.TICKET_USD, "MAX_OPEN": config.MAX_OPEN, "DAILY_LOSS_HALT_USD": config.DAILY_LOSS_HALT_USD,
           "FACTS": config.FACTS, "CODE_JUDGE": config.CODE_JUDGE, "EXIT": config.EXIT}
    os.makedirs("logs/shadow_ws", exist_ok=True)
    try:
        r = subprocess.run(["claude", "-p", "--model", MODEL, "--tools", "", "--strict-mcp-config",
                            "--no-session-persistence",
                            PROMPT.format(config=json.dumps(cfg, default=str), stats=json.dumps(s, default=str))],
                           cwd="logs/shadow_ws", capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        review = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else f"_AI review failed (rc {r.returncode})._"
    except subprocess.TimeoutExpired:
        review = "_AI review timed out._"
    day = time.strftime("%Y-%m-%d")
    doc = (f"# Sieve weekly review: {day} ({MODE}, last {days} days)\n\n"
           f"_The AI is told to argue against the setup. It changes nothing; you decide._\n\n"
           f"{config.scrub(review)}\n\n---\n\n## The numbers it was given\n\n```json\n"
           f"{json.dumps(s, indent=2, default=str)}\n```\n")
    open(OUT, "w").write(doc)
    open(OUT.replace(".md", f"_{day}.md"), "w").write(doc)
    m = re.search(r"## Verdict\s*\n+\**\s*(GO|HOLD|KILL)", review)
    print(f"WEEKLY REVIEW {m.group(1) if m else 'written'}: {OUT}")


if __name__ == "__main__":
    main()
