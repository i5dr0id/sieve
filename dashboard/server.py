# dashboard/server.py
# read-only monitor for the desk. reads the log files, never writes them, never touches the key.
#   cd desk && .venv/bin/python dashboard/server.py        -> http://127.0.0.1:8787
# binds to 127.0.0.1 only: nothing outside this Mac can reach it.
import csv, io, json, os, secrets, subprocess, sys, tarfile, time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import requests
import config                     # also chdirs into desk/

HOST, PORT = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", 8787))
HERE = os.path.dirname(os.path.abspath(__file__))
_cache: dict = {}
JUDGES = ("claude", "grok", "code")
# a fresh secret each start. the page reads it from /api/state (same-origin only; a
# cross-origin tab can't read that JSON), and must echo it to RESUME trading. pausing
# needs no token: it only ever makes the desk safer.
TOKEN = secrets.token_urlsafe(16)


def cached(key, ttl, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:
        val = hit[1] if hit else {"error": config.scrub(e)}
    _cache[key] = (time.time(), val)
    return val


def rows(path) -> list[dict]:
    return list(csv.DictReader(open(path))) if os.path.exists(path) else []


def tail(path, n) -> list[str]:
    if not os.path.exists(path):
        return []
    with open(path, errors="replace") as f:
        return [l.rstrip("\n")[:400] for l in f.readlines()[-n:]]


def followups(base) -> dict:
    fu = rows(f"{base}/followups.csv")

    def score(verdict, name, shadow=False):         # shadow = the AI judge that only watches
        done = [float(r[f"pct_{name}"]) for r in fu if r["verdict"] == verdict and r.get(f"pct_{name}")
                and (r["judge"] == "ai-shadow") == shadow]
        return {"n": len(done), "up": sum(1 for p in done if p > 0),
                "avg": sum(done) / len(done) if done else None}

    return {"rows": fu[-30:][::-1],
            "skip_6h": score("SKIP", "6h"), "skip_24h": score("SKIP", "24h"),
            "buy_6h": score("BUY", "6h"), "buy_24h": score("BUY", "24h"),
            "ai_skip_6h": score("SKIP", "6h", True), "ai_buy_6h": score("BUY", "6h", True)}


def live_pool(mint) -> dict:
    r = requests.get(f"https://api.dexscreener.com/tokens/v1/solana/{mint}", timeout=10)
    r.raise_for_status()
    pairs = [p for p in r.json() if (p.get("baseToken") or {}).get("address") == mint]
    if not pairs:
        return {"price": 0, "liq_usd": 0}
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    return {"price": float(p.get("priceUsd") or 0), "liq_usd": (p.get("liquidity") or {}).get("usd") or 0,
            "url": p.get("url"), "chg_h1": (p.get("priceChange") or {}).get("h1")}


def wallet() -> dict:
    r = requests.post(config.RPC_URL, timeout=10, json={"jsonrpc": "2.0", "id": 1, "method": "getBalance",
                                                         "params": [config.WALLET_ADDRESS]})
    sol = r.json()["result"]["value"] / 1e9
    q = requests.get("https://lite-api.jup.ag/swap/v1/quote", timeout=10, params={
        "inputMint": "So11111111111111111111111111111111111111112",
        "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "amount": 10**9, "slippageBps": 50}).json()
    px = int(q["outAmount"]) / 1e6
    return {"address": config.WALLET_ADDRESS, "sol": sol, "usd": sol * px, "sol_usd": px}


def runner() -> dict:
    # match on the pattern, not pgrep's -l label: under proot the label is truncated to
    # the ~15-char comm field (e.g. "/bin/ba"), so a substring check on it would miss.
    r = subprocess.run(["pgrep", "-f", "run.sh forever"], capture_output=True, text=True)
    running = r.returncode == 0 and bool(r.stdout.strip())
    return {"running": running, "args": "forever" if running else None, "active_mode": config.MODE}


def state(mode: str, day: str) -> dict:
    base = f"logs/{mode}"
    checks = rows(f"{base}/checks.csv")
    trades = rows(f"{base}/trades.csv")
    book = json.load(open(f"{base}/positions.json")) if os.path.exists(f"{base}/positions.json") else {}

    today = [r for r in checks if r["time"].startswith(day)]
    judged = {r["mint"] for r in checks if r["stage"] in JUDGES}
    pending = [r for r in checks if r["verdict"] == "REVIEW" and r["mint"] not in judged]
    down = [r for r in today if "failed:" in (r["reason"] or "")]
    kills = Counter(r["reason"] for r in today
                    if r["stage"] in ("facts", "pool", "limits") and "failed:" not in (r["reason"] or ""))

    positions = []
    for mint, p in book.items():
        lp = cached(f"pool:{mint}", 30, lambda m=mint: live_pool(m))
        price = lp.get("price") or 0
        positions.append({**p, "mint": mint, "now": price, "url": lp.get("url"), "liq_now": lp.get("liq_usd"),
                          "pct": (price / p["entry"] - 1) * 100 if price else None,
                          "upnl": p["qty"] * (price - p["entry"]) if price else None,
                          "hours": (time.time() - p["opened"]) / 3600})

    day_trades = [t for t in trades if t["time"].startswith(day)]
    realized = sum(float(t["pnl"]) for t in day_trades)
    closed = [t for t in day_trades if t["action"] != "open"]

    return {
        "mode": mode, "day": day, "now": time.strftime("%Y-%m-%d %H:%M:%S"),
        "paused": config.buys_paused(), "token": TOKEN,
        "runner": runner(),
        "wallet": cached("wallet", 60, wallet),
        "funnel": {
            "checked": len({r["mint"] for r in today if r["stage"] != "claude"}),
            "source_down": len(down),
            "killed_facts": sum(1 for r in today if r["stage"] == "facts" and r not in down),
            "killed_pool": sum(1 for r in today if r["stage"] == "pool" and r not in down),
            "killed_limits": sum(1 for r in today if r["stage"] == "limits"),
            "reviewed": sum(1 for r in today if r["verdict"] == "REVIEW"),
            "judge_skip": sum(1 for r in today if r["stage"] in JUDGES and r["verdict"] == "SKIP"),
            "bought": sum(1 for r in today if r["verdict"] == "BUY"),
        },
        "kills": kills.most_common(10),
        "pending": pending[-10:],
        "decisions": [r for r in checks if r["stage"] in JUDGES][-20:][::-1],
        "followups": followups(base),
        "recent": today[-40:][::-1],
        "positions": positions,
        "pnl": {"realized": realized, "unrealized": sum(p["upnl"] or 0 for p in positions),
                "closed": len(closed), "wins": sum(1 for t in closed if float(t["pnl"]) > 0)},
        "trades": trades[-50:][::-1],
        "log": tail(f"{base}/session.log", 80)[::-1],
    }


def export_blob(mode: str) -> bytes:
    """A .tar.gz of this mode's log files, for handing to Claude on the computer.
    Logs only (CSVs, positions, session log, reviews). Never the key or .env."""
    base = f"logs/{mode}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        if os.path.isdir(base):
            for name in sorted(os.listdir(base)):
                p = os.path.join(base, name)
                if os.path.isfile(p) and name.rsplit(".", 1)[-1] in ("csv", "json", "log", "md"):
                    tar.add(p, arcname=f"{mode}/{name}")
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def body_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def send(self, code, body: bytes, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            return self.send(200, open(os.path.join(HERE, "index.html"), "rb").read(), "text/html; charset=utf-8")
        if u.path == "/api/state":
            q = parse_qs(u.query)
            mode = q.get("mode", [config.MODE])[0]
            mode = mode if mode in ("paper", "live") else "paper"
            day = q.get("day", [time.strftime("%Y-%m-%d")])[0][:10]
            try:
                body = json.dumps(state(mode, day), default=str).encode()
                return self.send(200, body, "application/json")
            except Exception as e:
                return self.send(500, json.dumps({"error": config.scrub(e)}).encode(), "application/json")
        if u.path == "/api/export":
            q = parse_qs(u.query)
            mode = q.get("mode", [config.MODE])[0]
            mode = mode if mode in ("paper", "live") else config.MODE
            try:
                blob = export_blob(mode)
            except Exception as e:
                return self.send(500, json.dumps({"error": config.scrub(e)}).encode(), "application/json")
            fn = f"sieve-logs-{mode}-{time.strftime('%Y%m%d-%H%M')}.tar.gz"
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Disposition", f'attachment; filename="{fn}"')
            self.send_header("Content-Length", str(len(blob)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return self.wfile.write(blob)
        if u.path == "/manifest.webmanifest":
            return self.send(200, open(os.path.join(HERE, "manifest.webmanifest"), "rb").read(),
                             "application/manifest+json")
        if u.path == "/sw.js":
            return self.send(200, open(os.path.join(HERE, "sw.js"), "rb").read(),
                             "text/javascript; charset=utf-8")
        if u.path in ("/icon.png", "/icon-192.png", "/icon-512.png"):
            p = os.path.join(HERE, os.path.basename(u.path))
            if os.path.exists(p):
                return self.send(200, open(p, "rb").read(), "image/png")
        self.send(404, b"not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/pause":
            data = self.body_json()
            on = bool(data.get("on"))
            if not on and data.get("token") != TOKEN:          # resume needs the same-origin token; pause never does
                return self.send(403, json.dumps({"error": "bad token"}).encode(), "application/json")
            try:
                if on:
                    open(config.PAUSE_FLAG, "w").write(time.strftime("%Y-%m-%d %H:%M:%S"))
                elif os.path.exists(config.PAUSE_FLAG):
                    os.remove(config.PAUSE_FLAG)
                return self.send(200, json.dumps({"paused": config.buys_paused()}).encode(), "application/json")
            except Exception as e:
                return self.send(500, json.dumps({"error": config.scrub(e)}).encode(), "application/json")
        self.send(404, b"not found", "text/plain")


if __name__ == "__main__":
    print(f"Sieve dashboard on http://{HOST}:{PORT}  (ctrl+c to stop)")
    ThreadingHTTPServer((HOST, PORT), H).serve_forever()
