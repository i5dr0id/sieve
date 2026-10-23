# Sieve: next up

Written 2026-10-20. Start these once there are **2–3 weeks of live data, or 30+ closed trades**. Before that, every result is noise.

Already done on 2026-10-20:
- **Exit checks every minute** for open trades.
- **Empty token accounts closed** after each full sell, so their ~$0.21 deposits come back.
- **An AI judge in shadow mode** (`shadowjudge.py`): it records verdicts but never trades.

---

## 4. Re-tune the rules from the evidence

**Goal:** change rules only where the data says a rule is costing money or saving it.

**Data to use:**
- `logs/live/followups.csv`: price +6h and +24h after every verdict from the code judge and the AI shadow judge.
- `logs/live/trades.csv`: real fills, slippage and profit or loss.
- `logs/live/checks.csv`: every kill and the reason for it.

**Steps:**
- [ ] **Fix the backtest's "24h" label** in `backtest.py`. It measures the last price available, not 24 hours later. Either name the column after the hours it really covers, or require the full 24 hours and count tokens without enough data separately.
- [ ] **Run the backtest weekly** on all new tokens: `.venv/bin/python backtest.py`.
- [ ] **Score each code-judge rule** (`CODE_JUDGE` in `config.py`). For each rule, check what the tokens it skipped did over 6h and 24h:
  - `max_vol_to_liq_1h` (5×)
  - `sells_over_buys_1h`
  - `copycat_hours`
  - `require_website`

  If a rule's skips went up more often than they went down, loosen it or drop it. That's how the 200% rule was dropped.
- [ ] **AI judge versus rules.** Compare the AI shadow verdicts with the code judge on the same tokens. Show where they disagreed and who was right. Promote the AI judge to real buys only if it clearly wins over 30+ disagreements.
- [ ] **Sweep the exit settings** (`EXIT`) again, using live fills to set a realistic cost instead of the flat 5%.
  - The first sweep hinted that a −20% stop with a 20% trailing stop and a 3h time stop loses less.
  - Change only one setting at a time.
- [ ] Check whether the **13 checks' thresholds** (`FACTS`) are too strict. For example, the $30k minimum pool kills the most tokens. What did the $20–30k pools do afterwards?

**Done when:** each rule has a number next to it ("its skips averaged −X% after 24h"), and every change is noted in `config.py` with the date.

---

## 5. Time of day

**Goal:** find out whether some hours are clearly better or worse for entries, then either skip the bad hours or trade only the good ones.

**Data:** every verdict in `followups.csv` already has `hour_local` and `hour_ny`. Trades have timestamps.

**Steps:**
- [ ] Wait for **100+ judged tokens** first. With fewer, the hourly buckets hold 2–3 tokens each, which means nothing.
- [ ] Group by **New York hour** in blocks of 4 hours, because US traders drive a lot of memecoin volume. For each block, show:
  - tokens that passed the 13 checks;
  - +6h and +24h results for buys and skips;
  - the profit or loss of real trades.
- [ ] Also group by **weekday versus weekend**.
- [ ] Add a "by hour" chart to the dashboard: a bar chart, one bar per 4-hour block.
- [ ] If one block is clearly negative, add `NO_ENTRY_HOURS_NY = [...]` to `config.py` and a check in `book.guard()`. Exits keep running at all hours.

**Watch out:** the token's location can't be measured (tokens don't have a country), only the time. Look for a pattern that holds across several weeks, not one lucky day.

---

## 6. Better signals than DexScreener's lists

**Goal:** give the judge, whether rules or AI, information the 13 checks can't see. Today the desk sees a snapshot: pool size, 1-hour buys and sells, holders. It can't see the **trend**.

**Options:**

| Source | What it adds | Cost |
|---|---|---|
| **Birdeye API** | holder count over time, price and volume history, trader counts | free tier with an API key |
| **Helius API** | parsed transactions: who is buying, wallet ages, big holders moving | free tier with an API key |
| **GeckoTerminal** (already used in the backtest) | 5-minute candles, so the price trend and volatility before entry | free, ~30 calls/min |
| **Rugcheck** (already used) | the insider graph, already partly used | free |

**Steps:**
- [ ] **Start free:** use GeckoTerminal's 5-minute candles at decision time. Work out:
  - the trend over the last 1h and 6h;
  - whether the token is making higher lows;
  - how deep the drop from its high is.

  Give these to the AI shadow judge and log them in `followups.csv`.
- [x] **Birdeye free key added (2026-10-20)**, stored as `BIRDEYE_API_KEY` in `.env`, with a limit of 60 requests a minute.
  - `birdeye.py` gives a trend snapshot (holders, unique-wallet growth, buy and sell USD, price change from 5 minutes to 24 hours) to the AI shadow judge, and it's logged in `shadow.csv`'s `trend` column.
  - Not used by the code judge yet.
  - The free key **can't** read `token_security`. It **can** read price, overview, candles, holders and trades.
- [ ] **Holder and wallet growth as a rule:** once there's data, test whether `uniqueWallet1hChangePercent > 0` or `buy_share_usd_1h > 0.55` separates winners from losers.
  - Counts mislead: startupSI showed 4,718 buys against 1,099 sells, but in USD the split was 52% against 48%.
- [ ] **Liquidity trend:** is the pool growing or shrinking? Snapshot the pool size every scan and compare.
- [ ] **Smart-money wallets (Helius):** keep a list of wallets that keep buying early and selling green. A token those wallets buy is a strong signal. This is the biggest job, so do it last.
  - **Discussed 2026-10-22 (prototype deferred).** Use it two ways: (A) a confirmation signal on tokens that already passed the 13 checks — buy the survivors proven wallets also bought; (B) a discovery source — a tracked wallet's new buy enters the pipeline but still must pass all 13 checks. Rug filter stays in front, Sieve's own exits stay behind, so none of OdinBot-style blind-copy risk. NOT the same as copy-trading (OdinBot = blind copy + 1% fee + custody).
  - **How to qualify a wallet to copy:** win rate 55–70% (>90% = farming/wash red flag), positive realized PnL over 7/30d, profit spread across many tokens (not one moonshot), ≥30–50 closed trades, cuts losers, copyable hold time (mins–hours not 5s bots), NOT insider/bundler/deployer-linked (they sell into your buy), sells green. Fit: prefer selection-edge wallets over pure snipers (you enter after them). Rule: require **2+ tracked wallets** on the same token (consensus), re-score weekly (wallets go cold), never size up for a "whale".
  - **Detection:** read it off-chain via Helius. **Webhooks** (push, ~1 credit per actual trade event → ~15k/mo for 30 wallets, near-instant) beat **polling** the Enhanced Transactions API (`/v0/addresses/{addr}/transactions?type=SWAP`, ~170–260k/mo for 20–30 wallets at 5-min). A buy = swap where wallet's SOL/USDC down + target-token up (use net balance change). Free tier = 1M credits/mo, 10 req/s (rate limit is a non-issue; monthly credits is the cap, shared with the desk's own RPC). **Confirm the Enhanced-Tx API credit cost first** — modeled at 1/call; if 10/call only webhooks/5–10min polling survive.
  - Start **logged-only** (track candidate wallets, score them, log when a tracked wallet buys a token Sieve is already seeing); promote to a buy rule only after the data shows it separates winners from losers — same discipline as dropping the 200% rule.
- [ ] Each new signal starts as **logged only**. It becomes a rule only after #4 shows it separates winners from losers.

**Keys added 2026-10-20** (all in `.env`, loaded by `config.ENV`, removed from any error text by `config.scrub()`):
- **Helius:** in use as the **main RPC** (fastest from this Mac, about 430 ms against FluxRPC's ~1,000 ms). All Solana calls and trades go Helius → FluxRPC → public, whichever answers first.
  - Also available with this key, not used yet:
    - **DAS `getAsset`**: token metadata.
    - **`getTokenLargestAccounts`**: top holders.
    - **`getPriorityFeeEstimate`**: Jupiter's "auto" fee covers this today.
    - **Enhanced transactions** (`api.helius.xyz/v0/addresses/{addr}/transactions`): parsed swaps per wallet. This is the base for the **smart-money wallet** idea below.
- **FluxRPC:** in use as the backup RPC. Free plan: 10 GB a month.
- **Rugcheck key:** in use, sent as a header. The free plan allows 3 requests a second and returns cached reports only.
- **Solana Tracker:** **not used yet.** It has token, pools, risk, events, buys/sells and holders, but the free plan has only **2,500 credits a month, about 80 a day**.
  - It could run on tokens that pass the 13 checks only (~10 a day, ~300 a month).
  - It might also replace or check DexScreener for finding tokens, but that would use up the credits fast.
- **CoinGecko Demo key:** used as the **backup** for the backtest's price candles when GeckoTerminal rate-limits. It's the same data. The limit is ~30 calls a minute and ~10,000 a month, so don't make it the main source for a full backtest.
  - A good fit for item 6's "trend at decision time": about 10 tokens a day × 1–2 calls.
- **Unused so far:** the FluxRPC WebSocket and the "shield" keys.

**Remember:** API keys go in `desk/.env` (it's in `.gitignore`). Never put them in `config.py`.

---

## 7. Strategy competition (paper only)

Inspired by @0x_exit's "four traders compete" post (2026-10-20). Its 51× result is unverified. The useful parts:
- **Several entry styles running on the same token feed.**
- **The patient style won**, which matches the backtest: fresh tokens crash, and chasing a pump loses.

**Goal:** find out which *entry style* actually makes money on tokens that pass the 13 checks, before any of it touches real money.

**Strategies.** Each gets the same pretend $5 per trade and the **same exits**, so only the entry differs:

| Name | Enters when |
|---|---|
| `now` | the code judge says BUY. This is today's live behaviour and the baseline. |
| `pullback` | the price has dropped 20–40% from its high since we first saw it, then makes a higher 5-minute low |
| `survivor` | it has taken a ≥30% drop from a high and recovered half of it. "Survived its first big selloff." |
| `liq_growth` | the pool's liquidity is up ≥20% since first seen, and Birdeye shows unique wallets growing |

**Steps:**
- [ ] **Backtest first, free and fast.** Add the 4 entry styles to `backtest.py` and replay them on the cached 5-minute candles of every token that passed the 13 checks. Find out quickly whether any style beats `now`.
- [ ] **Then a live paper competition:**
  - `compete.py` watches every token that passed the 13 checks for up to 24 hours.
  - It enters each strategy on paper when that strategy's rule fires, and exits with the standard `EXIT` rules.
  - It writes `logs/live/compete.csv` with one row per strategy per trade.
  - Needs the GeckoTerminal or CoinGecko candles that item 6 adds.
- [ ] **Score weekly with equal money, no allocator.** The weekly review gets each strategy's P&L, hit rate and worst day.
- [ ] **An allocator only later.** After 4+ weeks, if one style clearly leads, test moving paper money towards it **weekly, not hourly**. Hourly moves reward luck, which is why the momentum bot in that post looked like the winner and then went broke.
- [ ] **Promotion to real money:** a style replaces `now` only after it beats it over **30+ paper trades**, and it starts at $5 per trade.

**Never:** let strategies trade real money directly, or let an allocator change real trade sizes.

---

## Done: PWA dashboard controls (2026-10-21)

For running the desk on the Nokia 7.1 phone and controlling it from the phone screen:
- **Stop/Resume buys button.** Writes/removes `logs/PAUSE_BUYS`. `config.buys_paused()` is checked at the top of `book.guard()`, which gates every buy (`check.py`, `verdict.py`, and `trade.py` right before the send). **Exits ignore the flag and keep running** — a paused desk still manages open positions. The flag is global across paper/live.
- **Export logs button.** `GET /api/export?mode=live` streams a `.tar.gz` of `logs/<mode>/` (CSVs, positions, session log, weekly review). For handing to Claude on the computer. Never includes `.env` or the key.
- **Resume needs a token** read from `/api/state` (same-origin only), so another browser tab can't re-enable trading. Pausing never needs it (it only makes the desk safer).
- **Installable PWA:** `manifest.webmanifest`, `sw.js` (network-only for `/api/*`, shell cached for offline), icons, apple-touch tags. Add-to-home-screen gives an app-like launcher.
- Still binds to `127.0.0.1`. On the phone the browser is on the same device, so no network exposure.

**Next for the phone (not done yet):** the Termux port itself — 3 swaps (`caffeinate`→`termux-wake-lock`, `date -j`→`date -d`, `osascript`→`termux-notification`), copy desk + `.env` + key over SSH (key file-to-file, never read), paper-test, stop the Mac copy, start the phone copy. Only one copy may run at a time (shared wallet). AI parts (shadow judge, weekly review) stay on the computer via the exported logs — opencode's free tier was unusable (hung, couldn't call tools) and `claude` needs a login.

---

## Done: weekly "CEO" review (2026-10-21)

From @bl888m's "team of bots" article, its "CEO seat whose job is to disagree":
- `weeklyreview.py` runs **every Monday just after midnight** from `run.sh`.
- It gathers the week's numbers and asks Claude (Sonnet, **no tools**) to argue against the setup: GO, HOLD or KILL, the rule to challenge, AI judge versus code judge, and one experiment with a pass/fail number.
- It writes `logs/live/WEEKLY_REVIEW.md` plus a dated copy, and sends a Mac notification. **It changes nothing.**
- Run it by hand any time: `.venv/bin/python weeklyreview.py 7`.

---

## Also noted (not 4–7)
- **Auto-start after a Mac restart** with launchd, for the desk, the dashboard and `notify.sh`. Today a reboot stops trading silently and leaves open trades unwatched.
- **Phone notifications** with ntfy or Telegram.
- **Moving to a server** (a VPS): replace `caffeinate`, `date -j` and `osascript`. **Only one copy may ever run at a time.**
- **Ticket size:** stay at $5 until there are 30+ closed live trades with a positive result.
