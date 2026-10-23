# Running Sieve on an Android phone (Termux + Debian proot)

An old always-on phone makes a cheap, low-power host. The one wrinkle: the `solders`
signing library ships **glibc** wheels, and Termux uses Bionic libc — so the desk runs
inside a **Debian proot** (glibc), not in Termux directly.

## One-time setup (type these in the Termux app, not over SSH)

```bash
pkg update -y
pkg install -y proot-distro rsync openssh termux-api
proot-distro install debian

# get the desk into the container (clone or copy sieve/ to /root/sieve inside Debian)
proot-distro login debian
  apt-get update && apt-get install -y python3 python3-venv git tzdata
  git clone <your sieve repo> /root/sieve && cd /root/sieve
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
  python newwallet.py            # creates /root/.sieve/hotwallet.json
  cp .env.example .env           # edit it
  ln -sf /usr/share/zoneinfo/<Your/Zone> /etc/localtime   # proot defaults to UTC
  exit
```

Then edit `DESK` in `sieve-start.sh` below to point at your container desk path
(default `/root/sieve`), and copy these three scripts to your Termux home (`~`).

## The scripts

- **`sieve-start.sh`** — holds a wake lock and launches the desk (engine + dashboard + notifier) inside the proot. Run: `bash ~/sieve-start.sh`.
- **`sieve-stop.sh`** — kill switch. Run: `bash ~/sieve-stop.sh`.
- **`sieve-boot.sh`** — put in `~/.termux/boot/` and install the **Termux:Boot** app (from F-Droid, opened once) to auto-start after a reboot.

## Notes

- **Only one copy may run at a time** against a wallet. Stop any other copy first.
- Set **Termux → Battery → Unrestricted** or Android may kill it.
- The dashboard binds `HOST=0.0.0.0` so you can open it from another device on your LAN at `http://<phone-ip>:8787`, or on the phone itself at `http://127.0.0.1:8787` (installable as a PWA).
- `termux-api` + the Termux:API app give you phone notifications on buys/sells/errors.
