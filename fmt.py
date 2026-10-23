# fmt.py
# turns check.py's json output into one line per token for session.log.
import sys, json, re, time

now = time.strftime("%H:%M")
for chunk in re.split(r"(?m)^(?=\{)", sys.stdin.read()):
    chunk = chunk.strip()
    if not chunk:
        continue
    try:
        v = json.loads(chunk)
    except Exception:
        print(now, "ERROR", chunk.replace("\n", " ")[:300]); continue
    if v["verdict"] == "REVIEW":
        t, p = v["token"], v["pool"]
        print(now, "REVIEW", t["mint"], v["symbol"], v["url"],
              f"liq=${p['liq_usd']:,.0f} age={p['age_min']}m b/s1h={p['buys_1h']}/{p['sells_1h']}",
              f"risk={t['risk_score']} top10={t['top10_pct']}% dev={t['dev_pct']}% warn={t['warn']}")
    else:
        print(now, "KILL", v.get("symbol"), v["stage"], v["reason"])
