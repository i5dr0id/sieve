# fills.py
# a BUY verdict becomes a position once per mode: live first (speed matters with real money), then paper.
# each runs enter.py in its own process, so it uses that mode's book, limits and pause switch.
import subprocess, sys


def enter_both(mint: str, symbol: str, price: float, liq_usd: float) -> list[str]:
    out = []
    for mode in ("live", "paper"):
        r = subprocess.run([sys.executable, "enter.py", mode, mint, symbol or "?", str(price), str(liq_usd)],
                           capture_output=True, text=True)
        out.append((r.stdout or r.stderr).strip() or f"{mode}: no output")
    return out
