# enter.py <paper|live> <mint> <symbol> <price> <liq_usd>
# one BUY verdict, one mode: check this mode's limits and pause switch, then fill (paper) or buy for real (live).
# called by fills.enter_both() for each mode. live results are also written to logs/live/session.log.
import os, sys, time
os.environ["SIEVE_MODE"] = sys.argv[1]             # before config: binds every path and limit to this mode
import config, book

mint, symbol, price, liq = sys.argv[2], sys.argv[3], float(sys.argv[4]), float(sys.argv[5])


def say(msg: str):
    print(msg, flush=True)
    if not config.PAPER:
        with open(config.SESSION_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M')} {msg}\n")


if (g := book.guard(mint)):
    say(f"{'PAPER' if config.PAPER else 'LIVE'} skip {symbol}: {g}")
elif config.PAPER:
    book.open_position(mint, symbol, price, liq)
    say(f"PAPER BUY ${config.TICKET_USD} of {symbol} at {price}")
else:
    import trade
    try:
        say(trade.enter(mint, symbol, {"price": price, "liq_usd": liq}))
    except trade.PriceRan as e:                    # nothing was sent: the price ran away after the judge looked
        say(f"LIVE skip {symbol}: {e}")
    except Exception as e:
        say(f"ERROR live buy {symbol} failed, nothing recorded: {config.scrub(e)}")
