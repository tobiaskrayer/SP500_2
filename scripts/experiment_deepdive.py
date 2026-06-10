"""
Deep-Dive der besten Varianten aus experiment_filters:
  - Jahres-Tabelle (Konsistenz, kein einzelnes Glücksjahr?)
  - Median vs. Mittelwert (tragen wenige Mega-Gewinner alles?)
  - Konzentrations-Check: Anteil der Top-1%-Trades am Gesamtertrag
  - Kombis Top-N + MACD (Tail-Reduktion)

Ausführen:  python -X utf8 -m scripts.experiment_deepdive
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from collections import defaultdict

from backtest.compare import get_date_data
from scripts.experiment_filters import select


def simulate_tk(date_data, bt_dates, **kwargs):
    trades = []
    for bt_date in bt_dates:
        dd = date_data.get(bt_date)
        if dd is None:
            continue
        for tk, td in select(dd["ticker_data"], **kwargs):
            trades.append({
                "date": str(bt_date), "ticker": tk,
                "p1m": td["p1m"], "spy_1m": dd["spy_perf_1m"],
            })
    return trades


def report(name, trades):
    t = [x for x in trades if x["p1m"] is not None and x["spy_1m"] is not None]
    arr = np.array([x["p1m"] for x in t])
    vs = np.array([x["p1m"] - x["spy_1m"] for x in t])

    print(f"\n{'='*78}\n{name}  (n={len(t)})\n{'='*78}")
    print(f"  Ret1M: Ø {arr.mean():+.2f}%  Median {np.median(arr):+.2f}%   "
          f"vs SPY: Ø {vs.mean():+.2f}%  Median {np.median(vs):+.2f}%")
    print(f"  Hit: {(arr > 0).mean()*100:.1f}%   Hit vs SPY: {(vs > 0).mean()*100:.1f}%   "
          f"Sharpe: {arr.mean()/arr.std():.3f}")

    # Konzentration: wie viel des Gesamtertrags steckt im obersten 1% der Trades?
    total = arr.sum()
    top1 = np.sort(arr)[-max(1, len(arr)//100):].sum()
    print(f"  Top-1%-Trades liefern {top1/total*100:.0f}% des Gesamtertrags" if total > 0 else "")

    per_year = defaultdict(list)
    for x in t:
        per_year[x["date"][:4]].append(x["p1m"] - x["spy_1m"])
    print(f"  {'Jahr':>6} {'n':>5} {'Ø vsSPY':>9} {'Median':>8}")
    for yr in sorted(per_year):
        v = np.array(per_year[yr])
        print(f"  {yr:>6} {len(v):>5} {v.mean():>+9.2f} {np.median(v):>+8.2f}")

    # Häufigste Ticker (Klumpenrisiko / Survivorship-Indikator)
    cnt = defaultdict(int)
    for x in t:
        cnt[x["ticker"]] += 1
    top = sorted(cnt.items(), key=lambda kv: -kv[1])[:10]
    print("  Häufigste Picks: " + ", ".join(f"{tk}({c})" for tk, c in top))


def main():
    bt_dates, date_data = get_date_data(years=10, step_weeks=2)

    report("v2-Baseline (top20 + Trend + nicht überkauft)",
           simulate_tk(date_data, bt_dates))
    report("v2 + Top-10 pro Datum",
           simulate_tk(date_data, bt_dates, top_n=10))
    report("v2 + Top-5 pro Datum",
           simulate_tk(date_data, bt_dates, top_n=5))
    report("v2 + MACD + Top-10 pro Datum",
           simulate_tk(date_data, bt_dates, require_macd=True, top_n=10))
    report("v2 + MACD + Top-5 pro Datum",
           simulate_tk(date_data, bt_dates, require_macd=True, top_n=5))


if __name__ == "__main__":
    main()
