"""
Experiment: Welche zusätzlichen Filter machen die Empfehlungen treffsicherer?

Testet Varianten auf den identischen angereicherten 10-Jahres-Daten
(cache/backtest/enriched_dd.pkl) gegen die v2-Baseline. Bewertet je Variante:
  - 1M/3M-Return, Trefferquote, vs SPY, Sharpe (Trade-Ebene)
  - Tail (p5, schlechtester Trade)
  - Korb-Ebene: % der Daten, an denen der Korb SPY schlägt
  - Jahres-Konsistenz: in wie vielen Jahren ist Ø vs SPY positiv?

Ausführen:  python -X utf8 -m scripts.experiment_filters
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from collections import defaultdict

from backtest.compare import get_date_data


def select(ticker_data: dict, *, rs_top_pct=0.20, require_trend=True,
           require_not_overbought=True, require_macd=False, min_vol_ratio=None,
           rsi_lo=None, rsi_hi=None, max_ext_ma50=None, rs_min_6m=0.0,
           top_n=None, vol_cap=None, rs_cap=None) -> list:
    """Flexible Auswahl-Logik — v2-Basis plus optionale Zusatzfilter."""
    cands = []
    for tk, td in ticker_data.items():
        row = td["row"]
        if require_trend and not (row.get("above_ma50") and row.get("above_ma200")):
            continue
        rsi = float(row.get("rsi", 50))
        if require_not_overbought:
            if rsi > 70 or not bool(row.get("bb_ok", True)):
                continue
        if rsi_lo is not None and rsi < rsi_lo:
            continue
        if rsi_hi is not None and rsi > rsi_hi:
            continue
        if require_macd and not bool(row.get("macd_bull", False)):
            continue
        if min_vol_ratio is not None and float(row.get("vol_ratio", 0) or 0) < min_vol_ratio:
            continue
        if max_ext_ma50 is not None:
            ma50 = float(row.get("ma50", float("nan")))
            close = float(row.get("close", float("nan")))
            if not np.isfinite(ma50) or ma50 <= 0 or close / ma50 > max_ext_ma50:
                continue
        vol = td.get("vol")
        if vol_cap is not None and vol is not None and vol > vol_cap:
            continue
        if rs_cap is not None and td["rs_score"] > rs_cap:
            continue
        cands.append((tk, td))
    if not cands:
        return []
    cutoff = float(np.percentile([c[1]["rs_score"] for c in cands], (1 - rs_top_pct) * 100))
    sel = [(tk, td) for tk, td in cands
           if td["rs_score"] >= cutoff and td["rs_6m"] >= rs_min_6m]
    if top_n is not None:
        sel = sorted(sel, key=lambda x: -x[1]["rs_score"])[:top_n]
    return sel


def simulate(date_data, bt_dates, **kwargs):
    trades = []
    for bt_date in bt_dates:
        dd = date_data.get(bt_date)
        if dd is None:
            continue
        for tk, td in select(dd["ticker_data"], **kwargs):
            trades.append({
                "date": str(bt_date),
                "p1m": td["p1m"], "p3m": td["p3m"],
                "spy_1m": dd["spy_perf_1m"], "spy_3m": dd["spy_perf_3m"],
            })
    return trades


def stats(trades):
    p1 = [t["p1m"] for t in trades if t["p1m"] is not None]
    p3 = [t["p3m"] for t in trades if t["p3m"] is not None]
    vs1 = [t["p1m"] - t["spy_1m"] for t in trades
           if t["p1m"] is not None and t["spy_1m"] is not None]
    if len(p1) < 50:
        return None

    arr = np.array(p1)
    # Korb-Ebene
    per_date = defaultdict(list)
    for t in trades:
        if t["p1m"] is not None and t["spy_1m"] is not None:
            per_date[t["date"]].append(t["p1m"] - t["spy_1m"])
    baskets = [np.mean(v) for v in per_date.values()]
    # Jahres-Konsistenz
    per_year = defaultdict(list)
    for t in trades:
        if t["p1m"] is not None and t["spy_1m"] is not None:
            per_year[t["date"][:4]].append(t["p1m"] - t["spy_1m"])
    years_pos = sum(1 for v in per_year.values() if np.mean(v) > 0)

    return {
        "n": len(p1),
        "picks_per_date": round(len(p1) / max(len(per_date), 1), 1),
        "ret1m": round(float(arr.mean()), 2),
        "hit1m": round(float((arr > 0).mean() * 100), 1),
        "vs_spy": round(float(np.mean(vs1)), 2) if vs1 else None,
        "sharpe": round(float(arr.mean() / arr.std()), 3) if arr.std() > 0 else None,
        "p5": round(float(np.percentile(arr, 5)), 1),
        "worst": round(float(arr.min()), 1),
        "ret3m": round(float(np.mean(p3)), 2) if p3 else None,
        "basket_beats": round(float(np.mean([1 if b > 0 else 0 for b in baskets]) * 100), 1) if baskets else None,
        "years_pos": f"{years_pos}/{len(per_year)}",
    }


VARIANTS = {
    # Baselines
    "v1-Aequivalent (top33, kein Strukturfilter)": dict(rs_top_pct=0.33, require_trend=False, require_not_overbought=False),
    "v2-Baseline (top20+Trend+nicht ueberkauft)":  dict(),
    # RS-Schaerfung
    "RS top15": dict(rs_top_pct=0.15),
    "RS top10": dict(rs_top_pct=0.10),
    "RS top5":  dict(rs_top_pct=0.05),
    # Zusatz-Signale auf v2
    "v2 + MACD bullisch":          dict(require_macd=True),
    "v2 + Volumen >= 1.2x":        dict(min_vol_ratio=1.2),
    "v2 + RSI 50-65":              dict(rsi_lo=50, rsi_hi=65),
    "v2 + max 10% ueber MA50":     dict(max_ext_ma50=1.10),
    "v2 + max 15% ueber MA50":     dict(max_ext_ma50=1.15),
    "v2 + rs_min_6m=5":            dict(rs_min_6m=5.0),
    "v2 + rs_min_6m=10":           dict(rs_min_6m=10.0),
    # Konzentration
    "v2 + Top-10 pro Datum":       dict(top_n=10),
    "v2 + Top-5 pro Datum":        dict(top_n=5),
    # Tail-Schutz (Retest mit korrigierten Daten)
    "v2 + Vola-Cap 60%":           dict(vol_cap=0.60),
    "v2 + Vola-Cap 45%":           dict(vol_cap=0.45),
    "v2 + Anti-Parabel RS<150":    dict(rs_cap=150.0),
    # Kombinationen
    "top15 + MACD":                dict(rs_top_pct=0.15, require_macd=True),
    "top15 + max15% ueber MA50":   dict(rs_top_pct=0.15, max_ext_ma50=1.15),
    "top15 + Vola-Cap 60%":        dict(rs_top_pct=0.15, vol_cap=0.60),
    "top15 + MACD + Vola60":       dict(rs_top_pct=0.15, require_macd=True, vol_cap=0.60),
}


def main():
    print("Lade 10-Jahres-Daten aus Cache...")
    bt_dates, date_data = get_date_data(years=10, step_weeks=2)
    print(f"{len(bt_dates)} Daten geladen.\n")

    header = (f"{'Variante':44} {'n':>6} {'p/Dat':>6} {'Ret1M':>7} {'Hit%':>6} "
              f"{'vsSPY':>7} {'Sharpe':>7} {'p5':>6} {'Worst':>7} {'Ret3M':>7} {'Korb%':>6} {'Jahre+':>7}")
    print(header)
    print("-" * len(header))
    for name, kwargs in VARIANTS.items():
        s = stats(simulate(date_data, bt_dates, **kwargs))
        if s is None:
            print(f"{name:44} -- zu wenige Trades --")
            continue
        print(f"{name:44} {s['n']:>6} {s['picks_per_date']:>6} {s['ret1m']:>+7.2f} {s['hit1m']:>6.1f} "
              f"{s['vs_spy']:>+7.2f} {s['sharpe']:>7.3f} {s['p5']:>6.1f} {s['worst']:>7.1f} "
              f"{s['ret3m']:>+7.2f} {s['basket_beats']:>6.1f} {s['years_pos']:>7}")


if __name__ == "__main__":
    main()
