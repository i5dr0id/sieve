# trade.py
# the only file that signs. Jupiter quote -> swap transaction -> sign with the hot wallet -> send.
# PAPER = True: everything is built, signed and simulated on-chain, nothing is sent.
#   python trade.py status                     wallet address, SOL balance
#   python trade.py dryrun-buy <mint> <usd>    full buy, simulated only
#   python trade.py roundtrip <usd> [--send]   SOL -> USDC -> SOL, the first live test (max $2)
#   python trade.py close-empty [--send]       close empty token accounts, get their deposits back
import base64, csv, json, os, sys, time
import requests
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction, Transaction
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.hash import Hash
from solders.pubkey import Pubkey
from config import (PAPER, RPC_URLS, WALLET_FILE, SLIPPAGE_BPS, MIN_SOL_RESERVE, TICKET_USD, LOG, scrub)
import book

JUP = "https://lite-api.jup.ag/swap/v1"
SOL = "So11111111111111111111111111111111111111112"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
HARD_MAX_USD = 10            # a typo in config.py still can't spend more than this on one buy
APPROVAL_WINDOW_MIN = 30     # a buy needs a BUY verdict in checks.csv from the last 30 minutes


def _wallet() -> Keypair:
    return Keypair.from_bytes(bytes(json.load(open(os.path.expanduser(WALLET_FILE)))))


def rpc(method: str, params: list):
    """Helius, then FluxRPC, then the public RPC, whichever answers first. Re-sending the same signed tx is harmless
    (same signature, it can only land once). Errors never carry the URL, so the key can't leak into a log."""
    for url in RPC_URLS:
        try:
            r = requests.post(url, timeout=30, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        except requests.RequestException as e:
            err = f"rpc {method}: {type(e).__name__}"
            continue
        if r.status_code >= 500 or r.status_code == 429:
            err = f"rpc {method}: HTTP {r.status_code}"
            continue
        if r.status_code != 200:
            raise RuntimeError(f"rpc {method}: HTTP {r.status_code}")
        d = r.json()
        if "error" in d:
            raise RuntimeError(scrub(f"rpc {method}: {d['error']}"))
        return d["result"]
    raise RuntimeError(err)


def sol_balance(pub) -> float:
    return rpc("getBalance", [str(pub)])["value"] / 1e9


def token_raw(pub, mint: str) -> int:
    accts = rpc("getTokenAccountsByOwner", [str(pub), {"mint": mint}, {"encoding": "jsonParsed"}])["value"]
    return sum(int(a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"]) for a in accts)


def decimals(mint: str) -> int:
    return rpc("getTokenSupply", [mint])["value"]["decimals"]


def quote(inp: str, out: str, amount_raw: int, slippage_bps: int | None = None) -> dict:
    r = requests.get(f"{JUP}/quote", timeout=20, params={
        "inputMint": inp, "outputMint": out, "amount": amount_raw, "slippageBps": slippage_bps or SLIPPAGE_BPS})
    r.raise_for_status()
    q = r.json()
    if "outAmount" not in q:
        raise RuntimeError(f"no route: {q}")
    return q


def sol_usd() -> float:
    return int(quote(SOL, USDC, 10**9)["outAmount"]) / 1e6


TOKEN_PROGRAMS = ("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA", "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb")


def close_empty(send: bool = True) -> dict:
    """Close every empty token account in the wallet. Each one holds a ~0.002 SOL deposit (rent)
    that comes back to the wallet on close. Simulated first; nothing is sent if the simulation fails."""
    kp = _wallet()
    owner = kp.pubkey()
    metas = []
    for prog in TOKEN_PROGRAMS:
        for a in rpc("getTokenAccountsByOwner", [str(owner), {"programId": prog}, {"encoding": "jsonParsed"}])["value"]:
            if a["account"]["data"]["parsed"]["info"]["tokenAmount"]["amount"] == "0":
                metas.append((Pubkey.from_string(a["pubkey"]), Pubkey.from_string(prog), a["account"]["lamports"]))
    if not metas:
        return {"closed": 0}
    metas = metas[:10]                                        # one transaction stays well under the size limit
    ixs = [Instruction(prog, bytes([9]), [AccountMeta(acct, False, True), AccountMeta(owner, False, True),
                                          AccountMeta(owner, True, False)]) for acct, prog, _ in metas]
    blockhash = Hash.from_string(rpc("getLatestBlockhash", [{"commitment": "finalized"}])["value"]["blockhash"])
    tx = Transaction([kp], Message.new_with_blockhash(ixs, owner, blockhash), blockhash)
    raw = base64.b64encode(bytes(tx)).decode()
    sim = rpc("simulateTransaction", [raw, {"encoding": "base64", "sigVerify": True}])["value"]
    out = {"accounts": len(metas), "rent_sol": sum(l for *_, l in metas) / 1e9, "sim_err": sim["err"]}
    if sim["err"] or not send:
        return {**out, "sent": False}
    sig = rpc("sendTransaction", [raw, {"encoding": "base64", "maxRetries": 3}])
    return {**out, "sent": True, "sig": sig}


# the Close button pays to land first: Jupiter's "veryHigh" priority fee, never more than 0.001 SOL
PRIORITY_FEE = {"priorityLevelWithMaxLamports": {"priorityLevel": "veryHigh", "maxLamports": 1_000_000}}


def _swap(q: dict, kp: Keypair, send: bool, priority: bool = False) -> dict:
    r = requests.post(f"{JUP}/swap", timeout=30, json={
        "quoteResponse": q, "userPublicKey": str(kp.pubkey()),
        "dynamicComputeUnitLimit": True, "prioritizationFeeLamports": PRIORITY_FEE if priority else "auto"})
    r.raise_for_status()
    unsigned = VersionedTransaction.from_bytes(base64.b64decode(r.json()["swapTransaction"]))
    tx = base64.b64encode(bytes(VersionedTransaction(unsigned.message, [kp]))).decode()
    if not send:
        sim = rpc("simulateTransaction", [tx, {"encoding": "base64", "sigVerify": True}])["value"]
        return {"sent": False, "sim_ok": sim["err"] is None, "sim_err": sim["err"],
                "logs": (sim.get("logs") or [])[-2:]}
    sig = rpc("sendTransaction", [tx, {"encoding": "base64", "maxRetries": 3}])
    for _ in range(30):
        st = rpc("getSignatureStatuses", [[sig]])["value"][0]
        if st and st.get("confirmationStatus") in ("confirmed", "finalized"):
            if st.get("err"):
                raise RuntimeError(f"tx failed on chain {st['err']}: https://solscan.io/tx/{sig}")
            return {"sent": True, "sig": sig}
        time.sleep(2)
    raise RuntimeError(f"not confirmed after 60s, check https://solscan.io/tx/{sig}")


def _changed(read, before, tries=15):
    """Balances can lag a confirmed tx by a few seconds: poll until `read()` moves off `before`."""
    for _ in range(tries):
        now = read()
        if now != before:
            return now
        time.sleep(2)
    return read()


def _approved(mint: str) -> bool:
    if not os.path.exists(LOG):
        return False
    cutoff = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - APPROVAL_WINDOW_MIN * 60))
    return any(r["mint"] == mint and r["verdict"] == "BUY" and r["time"] >= cutoff
               for r in csv.DictReader(open(LOG)))


def buy(mint: str, usd: float = TICKET_USD, dry: bool = False) -> dict:
    """Spend `usd` of SOL on `mint`. Returns the real fill: tokens, price per token, tx."""
    send = not (PAPER or dry)
    if usd > min(TICKET_USD, HARD_MAX_USD):
        raise RuntimeError(f"refused: ${usd} is over the ticket/hard cap")
    if send and not _approved(mint):
        raise RuntimeError("refused: no BUY verdict for this mint in the last 30 minutes")
    if send and (g := book.guard(mint)):
        raise RuntimeError(f"refused: limits say {g}")
    kp = _wallet()
    lamports = int(usd / sol_usd() * 1e9)
    bal = sol_balance(kp.pubkey())
    if send and bal - lamports / 1e9 < MIN_SOL_RESERVE:
        raise RuntimeError(f"refused: {bal:.4f} SOL leaves less than the {MIN_SOL_RESERVE} SOL fee reserve")
    q = quote(SOL, mint, lamports)
    before = token_raw(kp.pubkey(), mint) if send else 0
    res = _swap(q, kp, send)
    got = (_changed(lambda: token_raw(kp.pubkey(), mint), before) - before) if send else int(q["outAmount"])
    if got <= 0:
        raise RuntimeError(f"swap confirmed but no tokens arrived: {res}")
    qty = got / 10 ** decimals(mint)
    return {**res, "qty": qty, "price": usd / qty, "usd": usd, "sol_balance": bal}


def sell(mint: str, qty: float, everything: bool = False, dry: bool = False,
         slippage_bps: int | None = None, priority: bool = False) -> dict:
    """Sell `qty` tokens (or the whole balance) back to SOL. Returns usd received and price per token."""
    send = not (PAPER or dry)
    kp = _wallet()
    have = token_raw(kp.pubkey(), mint)
    raw = have if everything else min(have, int(qty * 10 ** decimals(mint)))
    if raw <= 0:
        raise RuntimeError("nothing to sell in the wallet")
    q = quote(mint, SOL, raw, slippage_bps)
    before = sol_balance(kp.pubkey())
    res = _swap(q, kp, send, priority)
    sol_out = (_changed(lambda: sol_balance(kp.pubkey()), before) - before) if send else int(q["outAmount"]) / 1e9
    usd = sol_out * sol_usd()
    return {**res, "usd": usd, "price": usd / (raw / 10 ** decimals(mint))}


def enter(mint: str, symbol: str, m: dict) -> str:
    """Live entry: real buy, then the book records the real fill (price, qty, tx) next to the screen price."""
    res = buy(mint, TICKET_USD)
    book.open_position(mint, symbol, res["price"], m["liq_usd"], TICKET_USD, screen_price=m["price"], tx=res["sig"])
    return f"LIVE BUY ${TICKET_USD} of {symbol} at {res['price']:.8g} (screen {m['price']:.8g}) https://solscan.io/tx/{res['sig']}"


def leave(mint: str, frac_of_original: float, screen_price: float, reason: str,
          slippage_bps: int | None = None, priority: bool = False, wait: float = 0) -> float:
    """Live exit: real sell of a fraction of the original size (>= 1.0 = everything). Returns realized pnl.
    one sell per token at a time: if another is running, wait up to `wait` s, then book.SellBusy (nothing sent)."""
    with book.sell_lock(mint, wait):
        p = book.load().get(mint)                    # re-read under the lock: the other seller may have closed it
        if not p:
            raise book.SellBusy(f"{mint[:8]} is already closed")
        everything = frac_of_original >= 1 or p["qty"] <= p["qty0"] * frac_of_original * 1.000001
        res = sell(mint, min(p["qty"], p["qty0"] * frac_of_original), everything=everything,
                   slippage_bps=slippage_bps, priority=priority)
        pnl = book.sell(mint, 1.0 if everything else frac_of_original, res["price"], reason,
                        screen_price=screen_price, tx=res["sig"])
    if everything:                                   # get the token account's deposit back. never blocks the exit
        try:
            time.sleep(4)                            # let the sell settle so the account reads empty
            close_empty()
        except Exception:
            pass
    return pnl


def roundtrip(usd: float, send: bool) -> list:
    """First live test, no memecoin involved: SOL -> USDC -> SOL. Proves signing and sending work."""
    if usd > 2:
        raise RuntimeError("roundtrip test is capped at $2")
    kp = _wallet()
    bal = sol_balance(kp.pubkey())
    lamports = int(usd / sol_usd() * 1e9)
    if bal - lamports / 1e9 < MIN_SOL_RESERVE:
        raise RuntimeError(f"wallet has {bal:.4f} SOL, needs {lamports / 1e9 + MIN_SOL_RESERVE:.4f}+")
    usdc0 = token_raw(kp.pubkey(), USDC)
    q1 = quote(SOL, USDC, lamports)
    r1 = _swap(q1, kp, send)
    if not send:
        return [r1, {"note": "leg 2 (USDC -> SOL) runs only after leg 1 is really sent"}]
    return [r1, *usdc_back(kp, _changed(lambda: token_raw(kp.pubkey(), USDC), usdc0)), {"sol_before": bal}]


def usdc_back(kp: Keypair, raw: int) -> list:
    """Leg 2 of the roundtrip: swap `raw` USDC back to SOL."""
    if raw <= 0:
        raise RuntimeError("no USDC in the wallet to swap back")
    before = sol_balance(kp.pubkey())
    r2 = _swap(quote(USDC, SOL, raw), kp, True)
    return [r2, {"sol_after": _changed(lambda: sol_balance(kp.pubkey()), before)}]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        pub = _wallet().pubkey()
        bal = sol_balance(pub)
        print(f"wallet {pub}\nSOL {bal:.4f} (~${bal * sol_usd():.2f})\nmode {'PAPER' if PAPER else 'LIVE'}")
    elif cmd == "dryrun-buy":
        print(json.dumps(buy(sys.argv[2], float(sys.argv[3]), dry=True), indent=2))
    elif cmd == "roundtrip":
        print(json.dumps(roundtrip(float(sys.argv[2]), send="--send" in sys.argv), indent=2))
    elif cmd == "close-empty":                # return the deposits of empty token accounts
        print(json.dumps(close_empty(send="--send" in sys.argv), indent=2))
    elif cmd == "usdc-back":                 # finish a roundtrip whose leg 2 failed
        kp = _wallet()
        print(json.dumps(usdc_back(kp, token_raw(kp.pubkey(), USDC)), indent=2))
