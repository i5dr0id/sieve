# sweep.py
# move live profit out of the bot's hot wallet to YOUR main wallet. the destination is fixed in .env
# (SWEEP_TO_ADDRESS) and nothing on the dashboard can change it, so the worst any sweep can do is pay you.
#   python sweep.py            send everything above SWEEP["keep_usd"] (the dashboard's Sweep button)
#   python sweep.py --weekly   the same, run by run.sh every Monday just after midnight
#   python sweep.py --test     send SWEEP["test_sol"] only, to check the address
#   python sweep.py --dry      build, sign and simulate the sweep, send nothing
import base64, csv, fcntl, os, sys, time
os.environ["SIEVE_MODE"] = "live"                # sweeps are real money only
import config, trade
from solders.pubkey import Pubkey
from solders.system_program import transfer, TransferParams
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash

S = config.SWEEP
LOG_CSV = "logs/live/sweeps.csv"
test, dry, weekly = "--test" in sys.argv, "--dry" in sys.argv, "--weekly" in sys.argv


def say(msg: str):
    print(msg, flush=True)
    if not dry:
        with open(config.SESSION_LOG, "a") as f:
            f.write(f"{time.strftime('%H:%M')} {msg}\n")


def main():
    if not config.SWEEP_TO:
        return say("SWEEP skipped: SWEEP_TO_ADDRESS is not set in .env")
    dest = Pubkey.from_string(config.SWEEP_TO)
    if not dest.is_on_curve():
        return say("SWEEP refused: SWEEP_TO_ADDRESS is not a normal wallet address")
    acct = trade.rpc("getAccountInfo", [config.SWEEP_TO, {"encoding": "base64"}])["value"]
    if acct and (acct["executable"] or acct["owner"] != "11111111111111111111111111111111"):
        return say("SWEEP refused: SWEEP_TO_ADDRESS is a program or token account, not a plain wallet")
    pending = os.path.exists(book_req := "logs/live/close_requests.json") and open(book_req).read().strip() not in ("", "[]")
    if pending:
        return say("SWEEP skipped: a close is in progress, try again in a minute")
    lock = open("logs/live/sweep.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return say("SWEEP skipped: another sweep is running")

    kp = trade._wallet()                          # only this process reads the key
    me = kp.pubkey()
    if dest == me:
        return say("SWEEP refused: the destination is the bot's own wallet")
    bal, px = trade.sol_balance(me), trade.sol_usd()
    keep = max(S["keep_usd"] / px, config.MIN_SOL_RESERVE)
    sol = S["test_sol"] if test else min(bal - keep - 0.00001, S["max_sol"])
    to = f"{config.SWEEP_TO[:4]}…{config.SWEEP_TO[-4:]}"
    if not test and sol * px < S["min_usd"]:
        return say(f"SWEEP nothing to send: wallet ${bal * px:.2f}, keeping ${S['keep_usd']} (min sweep ${S['min_usd']})")
    if bal - sol < config.MIN_SOL_RESERVE:
        return say(f"SWEEP refused: would leave less than the {config.MIN_SOL_RESERVE} SOL fee reserve")

    ix = transfer(TransferParams(from_pubkey=me, to_pubkey=dest, lamports=int(sol * 1e9)))
    blockhash = Hash.from_string(trade.rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"])
    raw = base64.b64encode(bytes(Transaction([kp], Message.new_with_blockhash([ix], me, blockhash), blockhash))).decode()
    sim = trade.rpc("simulateTransaction", [raw, {"encoding": "base64", "sigVerify": True}])["value"]
    if sim["err"]:
        return say(f"SWEEP refused: simulation failed {sim['err']}")
    if dry:
        return say(f"SWEEP dry run OK: would send {sol:.4f} SOL (${sol * px:.2f}) to {to}, keeping ${bal * px - sol * px:.2f}")
    sig = trade.rpc("sendTransaction", [raw, {"encoding": "base64", "maxRetries": 3}])
    for _ in range(30):
        st = trade.rpc("getSignatureStatuses", [[sig]])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            if st.get("err"):
                return say(f"ERROR SWEEP failed on chain {st['err']}: https://solscan.io/tx/{sig}")
            break
        time.sleep(2)
    else:
        return say(f"ERROR SWEEP not confirmed after 60s, check https://solscan.io/tx/{sig}")
    new = not os.path.exists(LOG_CSV)
    with open(LOG_CSV, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "kind", "sol", "usd", "to", "tx"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M"), "test" if test else "weekly" if weekly else "button",
                    round(sol, 6), round(sol * px, 2), config.SWEEP_TO, f"https://solscan.io/tx/{sig}"])
    say(f"SWEEP sent {sol:.4f} SOL (${sol * px:.2f}) to {to}{' (test)' if test else ''}, "
        f"wallet now ~${(bal - sol) * px:.2f} https://solscan.io/tx/{sig}")


try:
    main()
except Exception as e:
    say(f"ERROR SWEEP: {config.scrub(e)[:200]}")
