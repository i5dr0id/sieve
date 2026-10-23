#!/data/data/com.termux/files/usr/bin/bash
# Sieve kill switch. pkill -f is unreliable through proot, so collect PIDs and kill -9.
for pat in "run.sh forever" "phone-run.sh" "dashboard/server.py" "notify.sh" "proot-distro login debian"; do
  for p in $(pgrep -f "$pat"); do kill -9 "$p" 2>/dev/null; done
done
termux-wake-unlock 2>/dev/null || true
echo "sieve stopped"
