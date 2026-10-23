# Build prompt: "Sieve" — an auditable Solana memecoin trading desk

This is a complete, self-contained prompt you can hand to a capable coding agent (or
follow yourself) to build the bot in this repository from scratch. It specifies the
philosophy, architecture, exact rules, and safety requirements. Thresholds are the
defaults — they all live in one config file so they can be retuned later.

> ⚠️ This builds software that can place **real trades with real money**. It must default
> to **paper mode**, keep **hard caps in code**, and **never** commit or print secrets.
> It is not financial advice. Assume the operator can lose 100% of deployed funds.

---

## 1. Role and goal

Build a small, **auditable** command-line trading desk for Solana memecoins in **Python
3.11+**. The entire point is discipline a human lacks: **strict, mechanical entries and
exits**. Every token is run through a fixed rug/quality filter; a judge decides buy or
skip; position sizing is flat; and **all exits are decided in code before entry**. No
decision is made emotionally mid-trade. Favor clarity and smallness over cleverness —
a person should be able to read any file in a few minutes.

## 2. Guiding principles

1. **One config file.** Every number, threshold, and toggle lives in `config.py`. Retuning
   means editing that file and nothing else.
2. **Paper first.** `PAPER = True` by default. Paper and live write to **completely separate
   files** so a simulated position can never be mistaken for a real one.
3. **Entries strict, exits mechanical.** The filter is conservative; exits are fixed rules.
4. **Flat sizing.** Always the same dollar ticket. Never size off the last win/loss.
5. **Fail safe.** Any ambiguity or missing data → skip the trade, keep the position, or halt.
6. **Secrets never touch the repo or logs.** (See §4.)
7. **Every rule must be falsifiable.** Log enough to later measure whether each rule makes or
   loses money, and drop rules the data doesn't support.

## 3. Tech stack and constraints

- Python 3.11+, standard library where possible. Third-party deps: **`requests`** and
  **`solders`** (Solana keypair/transaction signing). That's it.
- No database — plain CSV and JSON files on disk.
- Dashboard uses only the standard library `http.server`.
- Runs on macOS and Linux (incl. a Debian proot on Android). Shell scripts must be portable.

## 4. Security requirements (non-negotiable)

- **Private key:** a utility creates a hot wallet and writes the secret key to
  `~/.sieve/hotwallet.json` (mode 600, directory 700) — **outside the repo**. The code only
  ever reads it to sign. The key is **never** printed, logged, or committed. Only the public
  address is ever shown.
- **API keys:** loaded from a `.env` file that is **gitignored**. Ship a `.env.example` with
  variable names and placeholders only. Provide a `scrub(text)` helper that removes every key
  value (and keys embedded in URLs) from any string before it is logged or displayed.
- **`.gitignore`** must exclude `.env`, `.venv/`, `__pycache__/`, `logs/`, and any
  `*hotwallet*.json`.
- The desk must run with **no keys set**, falling back to public endpoints (slower, rate-limited).

## 5. The pipeline (overview)

```
DexScreener feeds ─► 13 hard checks (code) ─► judge (code/AI) ─► buy ─► fixed exits
       scan            FACTS, ~2% survive       BUY / SKIP      flat $5   stop/ladder/trail/time/liq
```

A session loop runs roughly every 10 minutes: watch open positions, scan for new tokens,
run the judge on survivors, follow up on past verdicts. While any position is open, exits
are re-checked every 60 seconds.

## 6. Data sources (all have free tiers)

- **DexScreener** — token discovery and live pool data (price, liquidity, 1h buys/sells, age). No key.
- **Rugcheck** — risk score, LP lock, holder concentration, insider graph. Free key sent as a header.
- **Jupiter** (lite-api) — swap quotes and swap-transaction building.
- **Solana RPC** — balances, blockhash, simulate, send. Primary **Helius** (key in URL), with a
  backup RPC and a public fallback, tried in order; a dead/rate-limited endpoint falls through.
- **Birdeye** (optional) — trend data (wallet growth, buy/sell USD split) for the AI shadow judge only.
- **GeckoTerminal / CoinGecko** (optional) — historical candles for backtesting.

## 7. Modules to build

Each is a small single-purpose file.

- **`config.py`** — the single source of truth. Loads `.env` into an `ENV` dict, defines
  `scrub()`, all thresholds (§8–§11), file paths split by mode, and a `buys_paused()` helper
  that checks for a `logs/PAUSE_BUYS` flag file.
- **`newwallet.py`** — one-shot: create a keypair, save to `~/.sieve/hotwallet.json`
  (refuse if it already exists), print only the public address.
- **`market.py`** — fetch a token's pool snapshot from DexScreener.
- **`rugcheck.py`** — fetch and normalize a Rugcheck report (key as `X-API-KEY` header).
- **`scan.py`** — pull DexScreener feeds, dedupe against tokens already checked today.
- **`check.py`** — run the 13 checks (§8) on a token; write the verdict row to `checks.csv`.
- **`fmt.py`** — format scan output into readable KILL/REVIEW lines.
- **`verdict.py`** — given a survivor, call the judge; on BUY, call the trade entry.
- **`autojudge.py`** — the **code judge** (§9): judge any REVIEW that has waited past a threshold.
- **`grok.py`** — optional xAI judge (only if `JUDGE="grok"`). Holds the only xAI call.
- **`prompts.py`** — the judge prompt text (for AI judges).
- **`book.py`** — position bookkeeping: `guard()` (pre-trade limits, §11), open/close positions,
  today's P&L, positions stored in `positions.json`, trades appended to `trades.csv`.
- **`trade.py`** — live execution (§12): load keypair, Jupiter quote → build → sign → simulate →
  send, balance-change confirmation, close empty token accounts to reclaim rent. Own hard cap.
  CLI: `status`, `dryrun-buy <mint> <usd>`, `roundtrip`, `close-empty [--send]`.
- **`watch.py`** — for each open position, apply the exit rules (§10); on a full exit, reclaim rent.
- **`followup.py`** — after every verdict, record the token's price at +6h and +24h (to `followups.csv`).
- **`report.py`** — end-of-day summary from the logs.
- **`shadowjudge.py`** — an **AI judge that only watches** (§13): scores every survivor, logs to
  `shadow.csv`, **never trades**.
- **`weeklyreview.py`** — a weekly "CEO" review: feed the week's numbers to an AI told to argue
  *against* the current setup and output GO/HOLD/KILL. Changes nothing.
- **`backtest.py`** — replay historical candles to score rules and exits.
- **`dashboard/server.py`** + `index.html` + PWA assets — read-only monitor (§14).
- **`run.sh`** — the session loop. **`notify.sh`** — desktop/phone alerts. **`phone-run.sh`** — launcher for the Android/proot deployment.

## 8. The 13 hard checks (`FACTS` — code only, no AI)

A token must pass **all** of these or it is killed (recorded with the reason):

| Check | Default |
|---|---|
| Rugcheck risk score | ≤ 40 / 100 |
| LP locked or burned (largest pool) | ≥ 90% |
| Top-10 holders (pools & lockers excluded) | ≤ 30% |
| Dev wallet (supply still with creator) | ≤ 5% |
| Insider-flagged holders + insider-graph hits | 0 |
| Liquidity | ≥ $30,000 |
| Your ticket as a share of the pool | ≤ 1% |
| Minimum age | ≥ 30 minutes |
| Maximum age | ≤ 72 hours |

## 9. The judge (BUY vs SKIP)

Survivors go to a judge. Default is the **code judge** (`autojudge.py`); `JUDGE` can switch to
Claude or Grok. `CODE_JUDGE_AFTER_MIN` controls how long a REVIEW waits for an AI verdict before
the code judge steps in (0 = immediately, for unattended live running).

Code-judge rules — **each is a SKIP**; a token that breaks none is a **BUY** at the configured confidence:

- 1h volume > **5×** pool liquidity → skip (bot churn)
- more sells than buys in the last hour → skip (holders dumping)
- same ticker symbol seen under a different contract within **24h** → skip (copycat)
- no website → skip
- (optional, default **off**) price already up > X% in 1h → skip. *Off by default because backtesting
  showed it skipped winners — a worked example of letting evidence, not intuition, decide a rule.*

## 10. Exits (fixed in code before entry — `EXIT`)

- **Hard stop:** −35% from entry.
- **Take-profit ladder:** sell 50% at +100%, 25% at +200%.
- **Trailing stop:** the remainder exits if price falls 30% from its peak.
- **Time stop:** if not at least +20% after 6 hours, exit (dead money).
- **Liquidity stop:** if pool liquidity drops 40% from entry, exit now.
- If the pool is gone, attempt to sell everything. A failed sell keeps the position and retries.

## 11. Position and risk limits (`book.guard()` — checked before any buy, before any network call)

- Flat **$5** ticket.
- Max **3** open positions (≈ $15 at risk).
- Max **4** entries per day.
- **Daily loss halt:** realized loss today ≥ $10 → no new entries until tomorrow.
- **24h cooldown** per token after exiting it.
- Honor the **pause flag** (`logs/PAUSE_BUYS`): paused = no new buys, but exits keep running.

## 12. Trade execution (`trade.py`)

- Load the keypair from `WALLET_FILE`. Never log it.
- Buy: Jupiter quote (SOL→token) → build the swap transaction → **sign** → **simulate** → send.
- Confirm by polling the token balance change (quotes can lag a just-landed balance).
- Slippage cap **300 bps**; always keep **0.02 SOL** reserve for fees.
- A per-buy **hard cap** independent of ticket size (e.g. $10) that the code enforces regardless of config.
- After a full exit, close zero-balance token accounts to reclaim rent (finalized blockhash; simulate first).
- Provide a **dry-run** path that does everything except send.

## 13. Logging, files, and the shadow/review layer

- Split by mode: `logs/paper/…` and `logs/live/…`. Files: `checks.csv`, `trades.csv`,
  `positions.json`, `followups.csv`, `shadow.csv`, `session.log`. The desk creates these dirs on start.
- **Shadow judge:** an AI verdict on every survivor, logged and followed up like a real verdict, but it
  **never buys, never sells, never writes `checks.csv`**. Runs a headless model with all tools disabled.
- **Follow-ups:** +6h/+24h price after every verdict (code, AI, and shadow) — the raw material for
  deciding which rules actually work.
- **Weekly review:** once a week, hand the week's numbers to a stronger model instructed to disagree,
  and print GO / HOLD / KILL. It changes nothing; the operator decides.

## 14. Dashboard (`dashboard/server.py`)

- Read-only monitor over the log files. Binds `127.0.0.1` by default; `HOST=0.0.0.0` exposes it on the LAN.
- Shows: wallet balance, P&L (realized/unrealized), open positions, the day's funnel (checked → killed →
  reviewed → bought), recent decisions, follow-up scorecards, and the session log tail.
- All error text passes through `scrub()`.
- A **Stop/Resume button** that writes/removes the pause flag (resume requires a per-session token so a
  stray browser tab can't re-enable trading; pausing never needs it).
- An **Export button** that downloads the mode's logs as a `.tar.gz` (for off-device analysis). Never
  includes `.env` or the key.
- Ship it as an installable **PWA** (manifest + service worker; the service worker is network-only for
  `/api/*` so trading data is never served stale).

## 15. Run modes and CLI

- `run.sh forever` — loop until stopped, printing the prior day's report after each midnight.
- `run.sh HH:MM` — stop at a local time.
- Between scans, re-check exits every 60s while any position is open.
- Scripts must be portable across macOS and Linux (detect `date -j` vs `date -d`; pick the available
  notifier; skip AI steps when the AI CLI is absent).

## 16. Deliverables

All modules in §7, plus: `requirements.txt`, `.env.example`, `.gitignore`, a `README.md` with a prominent
risk disclaimer and setup steps, an MIT `LICENSE`, and the deployment scripts. Default `PAPER = True`.

## 17. Acceptance criteria

1. With no `.env`, the desk runs in paper mode against public endpoints without crashing.
2. `newwallet.py` creates a wallet, prints only the public address, and refuses to overwrite one.
3. `trade.py status` reads the balance read-only; `dryrun-buy` builds+signs+simulates without sending.
4. A token failing any of the 13 checks is killed with a logged reason and never reaches the judge.
5. `book.guard()` blocks a buy when any limit is hit or the pause flag is set; exits ignore the pause flag.
6. Paper and live never share a file.
7. No secret ever appears in a log, the dashboard, a commit, or stdout. `.env` is gitignored.
8. Every verdict gets a +6h/+24h follow-up, so any rule can later be scored on real outcomes.

## 18. Disclaimer to include in the README

State plainly: this trades real money, memecoins are extremely high-risk, you can lose everything, this is
not financial advice, use a disposable hot wallet with only losable funds, run paper first, and the authors
take no responsibility for losses.
