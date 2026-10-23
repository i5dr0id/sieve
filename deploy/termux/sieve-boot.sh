#!/data/data/com.termux/files/usr/bin/bash
# Termux:Boot startup. Put this in ~/.termux/boot/ and install the Termux:Boot app.
termux-wake-lock 2>/dev/null || true
pgrep -x sshd >/dev/null 2>&1 || sshd         # optional: SSH for remote management
sleep 25                                       # let Wi-Fi/data come up (the desk retries anyway)
if ! pgrep -f "run.sh forever" >/dev/null 2>&1; then
  setsid nohup bash "$HOME/sieve-start.sh" >>"$HOME/sieve-launch.log" 2>&1 </dev/null &
fi
