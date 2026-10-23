#!/data/data/com.termux/files/usr/bin/bash
# Sieve launcher (Termux side): hold a wake lock, then run the desk inside the Debian proot.
DESK=/root/sieve                     # <-- path to the desk INSIDE the Debian container
termux-wake-lock 2>/dev/null || true
# native Termux notifier (tails the desk log inside the container); optional
if [ -x "$HOME/sieve-notify.sh" ]; then
  pgrep -f sieve-notify.sh >/dev/null 2>&1 || setsid nohup bash "$HOME/sieve-notify.sh" >/dev/null 2>&1 </dev/null &
fi
exec proot-distro login debian -- /bin/bash "$DESK/phone-run.sh"
