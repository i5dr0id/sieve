# Sieve

A small, auditable Solana memecoin trading desk. Sieve's whole idea is **strict entries, mechanical exits**: every token runs a fixed set of rug/quality checks, a judge decides buy or skip, and the exits are decided *in code before you ever enter* — nothing is decided emotionally mid-trade. Every number lives in one file (`config.py`).

It started as a Python adaptation of a rug-filter approach shared by **boan** on X, then grew a code judge, fixed exits, a dashboard, and an optional AI "shadow" judge.

> ⚠️ **READ THIS FIRST — real money, real risk.**
> This software can place **real trades with real funds** on Solana. Memecoins are extremely high-risk; **you can lose 100% of what you put in.** This is **not financial advice**, it is not a guarantee of profit, and the authors take **no responsibility** for your losses. Use a **throwaway hot wallet with only money you can afford to lose entirely**, and **run it in paper mode first** until you understand exactly what it does. You are solely responsible for complying with the laws and regulations that apply to you.

---

## How it works

```
DexScreener feeds
      │
      ▼
13 hard checks  (FACTS in config.py — rugcheck + pool data, code only)
      │  ~2% survive
      ▼
judge  (code rules, or Claude/Grok)  →  BUY or SKIP
      │
      ▼
flat $5 ticket  →  fixed exits (stop, take-profit ladder, trailing, time, liquidity)
```

- **The 13 checks** (rug filter): risk score, LP locked, top-10 holder %, dev wallet %, insiders, liquidity, age, ticket-vs-pool share. All code, no AI.
- **The judge** decides BUY/SKIP on the survivors. Default is the **code judge** (fixed rules). Optionally Claude or Grok.
- **Exits are fixed before entry**: hard stop, a take-profit ladder, a trailing stop, a time stop, and a liquidity-drop stop.
- **An optional AI "shadow" judge** scores every survivor but **never trades** — purely for research.
- **A dashboard** (`dashboard/server.py`) shows live state, with a **Stop button** and a **log export**.

See `config.py` for every rule and threshold, and `TODO.md` for the roadmap. To understand or rebuild Sieve from first principles, `BUILD_PROMPT.md` is a complete spec/prompt that recreates it from scratch.

## Setup

Requires Python 3.11+.

```bash
git clone git@github.com:<you>/sieve.git
cd sieve
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 1. create a throwaway hot wallet (key saved to ~/.sieve/hotwallet.json, outside the repo)
.venv/bin/python newwallet.py          # prints your PUBLIC address

# 2. configure
cp .env.example .env                    # then edit .env: add your WALLET_ADDRESS and any API keys
#    free keys worth getting: Helius (RPC) and Rugcheck. Everything else is optional.

# 3. fund the wallet with a SMALL amount of SOL (send to the public address from step 1)
```

## Running

**Start in paper mode.** In `config.py` set `PAPER = True`. Paper and live use completely separate log files, so a pretend position can never be mistaken for a real one.

```bash
.venv/bin/python trade.py status        # sanity check: wallet + balance (read-only)
./run.sh forever                        # the desk: scan, judge, buy, watch exits. runs until stopped.
#   ./run.sh 00:00                       # or stop at a given local time
.venv/bin/python dashboard/server.py    # dashboard at http://127.0.0.1:8787
#   HOST=0.0.0.0 .venv/bin/python dashboard/server.py   # reachable from other devices on your LAN
./notify.sh                             # optional desktop/phone notifications on buys/sells/errors
```

Only ever run **one copy at a time** against a given wallet.

Going live: once you trust it in paper, set `PAPER = False`. Hard caps stay in the code (`trade.py` has its own per-buy cap; `config.py` sets ticket size, max open, daily loss halt, cooldown).

## The rules (defaults — all in `config.py`)

- **Entry limits:** $5 flat ticket, max 3 open, max 4 entries/day, daily-loss halt at $10, 24h cooldown per token.
- **Rug filter:** risk ≤40/100, LP ≥90% locked, top-10 ≤30%, dev ≤5%, 0 insiders, liquidity ≥$30k, age 30min–72h, ticket ≤1% of pool.
- **Exits:** stop −20%, sell half at +100% & a quarter at +200%, 30% trailing stop, 6h time stop if not +20%, exit if pool liquidity drops 40%.

To retune, you edit `config.py` and nothing else.

## Running on a phone (optional)

Sieve runs well on an always-on Android phone via **Termux + a Debian proot** (needed because the `solders` signing library ships glibc wheels). See `deploy/termux/` for the launcher, kill-switch, and boot scripts. The dashboard is a PWA you can "Add to Home screen".

## Security notes

- Your **private key never enters the repo** — `newwallet.py` writes it to `~/.sieve/hotwallet.json` (owner-only), and the code only ever reads it to sign.
- **API keys live in `.env`**, which is gitignored. The code scrubs key values out of any error text.
- Never paste your private key or seed phrase anywhere. Treat the hot wallet as disposable.

## License

MIT — see `LICENSE`. No warranty. Trade at your own risk.
