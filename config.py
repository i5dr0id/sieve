# config.py
# every number on the desk lives here. when you retune, you edit this file and nothing else.
import os

# run from this folder no matter where cron/launchd starts us, so the csv/json files land here
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# API keys live in .env (never in this file, never printed). scrub() blanks them out of any error text.
ENV = {}
if os.path.exists(".env"):
    for _line in open(".env"):
        if "=" in _line and not _line.lstrip().startswith("#"):
            _k, _v = _line.rstrip("\n").split("=", 1)
            ENV[_k.strip()] = _v.strip().strip("\"'")


def scrub(text) -> str:
    text = str(text)
    for v in ENV.values():
        if len(v) >= 12:
            text = text.replace(v, "***")
            if "key=" in v:                                   # the bare key inside a URL like ...?key=abc
                text = text.replace(v.split("key=", 1)[1].split("&")[0], "***")
    return text

MODEL = "grok-4.7"          # check console.x.ai -> Models if the API rejects it
PAPER = False               # LIVE since 2026-10-20. paper settings saved in logs/config_paper_backup.py

# the engine runs BOTH modes every cycle: run.sh sets SIEVE_MODE for each step. PAPER above is only the
# default for commands you type yourself, like `python trade.py status`.
if os.environ.get("SIEVE_MODE") in ("paper", "live"):
    PAPER = os.environ["SIEVE_MODE"] == "paper"
PAPER_LIMITS = False        # False: paper fills every BUY verdict (the most data). MAX_OPEN, entries/day and the
                            # loss halt are live-money rules. True: paper obeys them too, to copy live exactly.

TICKET_USD = 5              # flat. never sized off the last win
MAX_OPEN = 2                # 2 x $5 = $10 in the market, max (was 3 until 2026-10-27)
MAX_ENTRIES_PER_DAY = 4
DAILY_LOSS_HALT_USD = 7     # live realized loss today hits this -> no new live entries until tomorrow. paper keeps going
COOLDOWN_HOURS = 24         # no re-entry into a token you just left

FACTS = {                   # the rug filter. code only, no model
    "max_risk_score": 40,       # rugcheck score_normalised, 0-100, higher = riskier
    "min_lp_locked_pct": 90,    # biggest pool: LP locked or burned
    "max_top10_pct": 30,        # top 10 holders, pools and lockers excluded
    "min_top10_pct": 1,         # top 10 holding less than this = supply split across look-alike wallets (DOAS, startupSI). 2 cut a winner in the backtest
    "kill_warns": ["High holder correlation"],   # rugcheck warnings treated as kills: many holder wallets are one owner
    "max_dev_pct": 5,           # supply still sitting in the creator wallet
    "max_insiders": 0,          # insider-flagged holders + insider graph hits
    "min_liquidity_usd": 30000,
    "max_ticket_share": 0.01,   # your ticket is never more than 1% of the pool
    "min_age_min": 30,          # younger than this, every report is still guessing
    "max_age_hours": 72,
}

JUDGE = "claude"          # "grok" = xAI API call. "claude" = survivors wait for a Claude Code read
MIN_CONFIDENCE = 0.7

# code judge: steps in when a REVIEW has waited this long with no Claude/Grok verdict. None = never.
CODE_JUDGE_AFTER_MIN = 0         # live: nobody is watching, judge right away
CODE_JUDGE = {                  # each rule is a SKIP. a token that breaks none of them is a BUY at CONFIDENCE
    "max_chg_1h_pct": None,         # off: the backtest showed this rule skipping winners. a number turns it back on
    "max_vol_to_liq_1h": 10,        # 1h volume over 10x the pool = bot churn. was 5: backtest 2026-10-24 showed 5 skipping the winners
    "min_vol_to_liq_1h": 0.1,       # 1h volume under 0.1x the pool = a climb nobody is trading (fake climb)
    "sells_over_buys_1h": True,     # more sells than buys in the last hour = holders dumping
    "copycat_hours": 24,            # same symbol seen under another contract within this window
    "require_website": True,
    "confidence": 0.7,
}        # Grok says BUY below this -> treated as SKIP

# AI judge in shadow mode: verdicts are logged and followed up, never traded. None = off.
# runs headless Claude Code with every tool off; uses your Claude plan's usage (~10 calls a day).
SHADOW_JUDGE = {"model": "haiku", "timeout_s": 120}

EXIT = {
    "stop_pct": -35,                        # hard stop from entry
    "ladder": [(100, 0.50), (200, 0.25)],   # +100% sells half, +200% sells a quarter (of the original). after a
                                            # manual sale, each step sells the same share of what is left instead
    "trail_pct": 30,                        # the rest: out when price falls 30% from its peak
    "time_stop_hours": 4,                   # not up 20% after 4 hours -> out, dead money
    "time_stop_min_pct": 20,
    "late_trail_pct": 20,                   # past the time stop, no ladder sale yet: out when price falls 20% from its peak
    "liq_drop_pct": 40,                     # pool liquidity down 40% from entry -> out now
}

# live trading (only used when PAPER = False). trade.py also has its own hard cap per buy.
RPC_PUBLIC = "https://api.mainnet-beta.solana.com"
# tried in this order; a dead or rate-limited endpoint falls through to the next. keys sit inside the URLs,
# so these are never printed (config.scrub() blanks them in errors). Helius measured fastest from this Mac.
RPC_URLS = [u for u in (f"https://mainnet.helius-rpc.com/?api-key={ENV['HELIUS_API_KEY']}" if ENV.get("HELIUS_API_KEY") else None,
                        ENV.get("FLUXRPC_RPC"), RPC_PUBLIC) if u]
RPC_URL = RPC_URLS[0]
RUGCHECK_KEY = ENV.get("RUGCHECK_API")             # sent as a header, so it never ends up in a URL or a log
WALLET_ADDRESS = ENV.get("WALLET_ADDRESS") or "YOUR_WALLET_PUBLIC_ADDRESS_HERE"   # your bot wallet's PUBLIC address (set in .env). dashboard reads balance from it.
WALLET_FILE = "~/.sieve/hotwallet.json"   # the bot's key. never printed, never pasted
SLIPPAGE_BPS = 300          # 3% max slippage per swap; above this the swap fails instead of filling badly
MIN_SOL_RESERVE = 0.02      # always leave this much SOL for fees, never spend it

# profit sweeps (sweep.py): only ever to YOUR wallet, set as SWEEP_TO_ADDRESS in .env. the dashboard can't change it.
SWEEP_TO = ENV.get("SWEEP_TO_ADDRESS")
SWEEP = {"keep_usd": 18,    # leave this much in the bot: 2 tickets, the fee reserve and a couple of losses
         "min_usd": 3,      # don't bother sending less than this
         "max_sol": 0.5,    # hard cap per sweep
         "test_sol": 0.005} # sweep.py --test

# paper and live never share a file, so a pretend position can never be treated as a real one
MODE = "paper" if PAPER else "live"
LOG = f"logs/{MODE}/checks.csv"
POSITIONS = f"logs/{MODE}/positions.json"
TRADES = f"logs/{MODE}/trades.csv"
SESSION_LOG = f"logs/{MODE}/session.log"
FOLLOWUPS = f"logs/{MODE}/followups.csv"
SHADOW = f"logs/{MODE}/shadow.csv"         # the AI judge that only watches (shadowjudge.py)
PAUSE_FLAG = f"logs/{MODE}/PAUSE_BUYS"     # if this file exists, no NEW buys in this mode. exits keep running. the dashboard sets it.
DECISIONS = "logs/paper/checks.csv"        # every check and verdict, both modes: the scan and judges run once, logged as paper
os.makedirs(f"logs/{MODE}", exist_ok=True)


def buys_paused(mode: str | None = None) -> bool:
    """True when the dashboard has paused new entries for this mode. Checked in book.guard(); exits never check it."""
    return os.path.exists(f"logs/{mode or MODE}/PAUSE_BUYS")
