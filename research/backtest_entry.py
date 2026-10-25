# research/backtest_entry.py
# two entry rules from the ASSETS dump (2026-10-25), tested on top of the current code judge:
#   minimum token age, and "crashed in the hour before" (biggest peak-to-trough fall in the 60 min before the check).
#   python research/backtest_entry.py [logs_dir ...]
# read-only: public price data, no wallet, no trading.
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_filters import simulate, usd
from backtest_judge import build, judge_buys


def crash_1h(t):
    """biggest fall from a running high to a later low in the hour before the check, in % (0 = never fell)."""
    peak, worst = 0.0, 0.0
    for ts, o, h, l, c, v in t["hour_before"]:
        peak = max(peak, h)
        if peak > 0:
            worst = min(worst, (l / peak - 1) * 100)
    return -worst


def row(name, lst):
    if not lst:
        return f"   {name:34}    0"
    r = [usd(simulate(t["entry"], t["path"])[0]) for t in lst]
    return (f"   {name:34} {len(lst):>4}  won {sum(x > 0 for x in r) / len(r) * 100:>3.0f}%  "
            f"${sum(r):+7.2f} total  ${sum(r) / len(r):+.2f}/trade")


def main():
    have = build(sys.argv[1:] or ["logs/phone_snapshot/live", "logs/phone_snapshot/paper"])
    for t in have:
        t["crash"] = crash_1h(t)
    for label, pop in (("THE CODE JUDGE'S BUYS (cap 10x + new filters)", judge_buys(have)),
                       ("EVERY TOKEN THAT PASSED THE 13 CHECKS (bigger sample)", have)):
        print(label)
        print(row("baseline", pop))
        for age in (45, 60, 90, 120):
            cut = [t for t in pop if t["age_min"] < age]
            print(row(f"min age {age}m: removes", cut) + "   -> keeps" + row("", [t for t in pop if t not in cut])[38:])
        for dd in (40, 50, 60, 70):
            cut = [t for t in pop if t["crash"] >= dd]
            print(row(f"crashed {dd}%+ in prior hour: removes", cut) + "   -> keeps" + row("", [t for t in pop if t not in cut])[38:])
        print()
    print("THE JUDGE'S BUYS, ONE BY ONE")
    for t in sorted(judge_buys(have), key=lambda t: t["age_min"]):
        r, why = simulate(t["entry"], t["path"])
        print(f"   {t['symbol'][:12]:12} age {t['age_min']:>5}m  crashed {t['crash']:>3.0f}% in prior hour  "
              f"max {t['max_pct']:+6.0f}%  {why:13} ${usd(r):+6.2f}")


if __name__ == "__main__":
    main()
