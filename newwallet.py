# newwallet.py
# creates the desk's hot wallet. run it yourself, once, in your own terminal.
# the key goes to ~/.mtrades/hotwallet.json (outside the project, owner-only). only the public address is printed.
import json, os, stat
from solders.keypair import Keypair

DIR = os.path.expanduser("~/.mtrades")
PATH = os.path.join(DIR, "hotwallet.json")

if os.path.exists(PATH):
    raise SystemExit(f"{PATH} already exists. refusing to overwrite a wallet that may hold funds.")

os.makedirs(DIR, mode=0o700, exist_ok=True)
kp = Keypair()
fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
with os.fdopen(fd, "w") as f:
    json.dump(list(bytes(kp)), f)       # same format as solana-keygen, importable into Phantom

print("hot wallet created")
print("public address (safe to share, send SOL here):", kp.pubkey())
print("key file (never share, never paste anywhere):", PATH)
