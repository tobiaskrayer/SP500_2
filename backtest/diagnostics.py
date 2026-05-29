"""
Diagnostik für Backtest-Ergebnisse.

Wertet die Trade-Liste aus run_backtest()/results.json aus, um Schwachstellen
der aktuellen Empfehlungslogik aufzudecken. Kernfragen:

  1. Haben die Gates überhaupt Vorhersagekraft? (höherer tech_score / rs_score
     ⟹ bessere Forward-Rendite?)
  2. In welchen Marktphasen/Jahren versagt die Logik?
  3. Wie sieht das Verlust-Tail aus (Asymmetrie, Crash-Trades)?
  4. Schlägt der Empfehlungs-Korb den SPY konsistent oder nur im Mittel?

Reine Auswertung — kein Netzwerk, kein State.
"""

import json
import os
import statistics as _stats
from collections import defaultdict

_RESULTS_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest", "results.json")


def _avg(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _hit_rate(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(1 for v in vals if v > 0) / len(vals) * 100, 1) if vals else None


def _sharpe(vals):
    vals = [v for v in vals if v is not None]
    if len(vals) < 5:
        return None
    mean = sum(vals) / len(vals)
    sd = _stats.pstdev(vals)
    return round(mean / sd, 2) if sd > 0 else None


def _percentiles(vals, ps=(5, 25, 50, 75, 95)):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return {p: None for p in ps}
    out = {}
    for p in ps:
        k = (len(vals) - 1) * p / 100
        lo = int(k)
        hi = min(lo + 1, len(vals) - 1)
        out[p] = round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 2)
    return out


def analyze(result: dict) -> dict:
    """Berechnet alle Diagnose-Kennzahlen aus einem Backtest-Ergebnis."""
    trades = [t for t in result.get("trades", []) if t.get("perf_1m") is not None]
    if not trades:
        return {"error": "Keine messbaren Trades."}

    perfs = [t["perf_1m"] for t in trades]
    vs_spy = [t["vs_spy_1m"] for t in trades if t.get("vs_spy_1m") is not None]

    # ── 1. Nach Jahr ──────────────────────────────────────────────────────────
    by_year = {}
    yr_groups = defaultdict(list)
    for t in trades:
        yr_groups[t["date"][:4]].append(t)
    for yr in sorted(yr_groups):
        g = yr_groups[yr]
        by_year[yr] = {
            "n": len(g),
            "avg_perf_1m": _avg([x["perf_1m"] for x in g]),
            "hit_rate": _hit_rate([x["perf_1m"] for x in g]),
            "avg_vs_spy": _avg([x.get("vs_spy_1m") for x in g]),
            "sharpe": _sharpe([x["perf_1m"] for x in g]),
        }

    # ── 2. Nach tech_score-Bucket (validiert Gate 3) ───────────────────────────
    by_tech = {}
    tech_groups = defaultdict(list)
    for t in trades:
        ts = t.get("tech_score")
        if ts is None:
            continue
        # Buckets entsprechen den möglichen k/6-Werten
        bucket = f"{round(ts*6)}/6 ({ts*100:.0f}%)"
        tech_groups[bucket].append(t)
    for b in sorted(tech_groups):
        g = tech_groups[b]
        by_tech[b] = {
            "n": len(g),
            "avg_perf_1m": _avg([x["perf_1m"] for x in g]),
            "hit_rate": _hit_rate([x["perf_1m"] for x in g]),
            "avg_vs_spy": _avg([x.get("vs_spy_1m") for x in g]),
        }

    # ── 3. Nach rs_score-Quartil (validiert Gate 2) ────────────────────────────
    by_rs = {}
    rs_vals = sorted(t["rs_score"] for t in trades if t.get("rs_score") is not None)
    if len(rs_vals) >= 8:
        q1 = rs_vals[len(rs_vals) // 4]
        q2 = rs_vals[len(rs_vals) // 2]
        q3 = rs_vals[3 * len(rs_vals) // 4]

        def rs_bucket(v):
            if v <= q1:
                return "Q1 (niedrigste RS)"
            if v <= q2:
                return "Q2"
            if v <= q3:
                return "Q3"
            return "Q4 (höchste RS)"

        rs_groups = defaultdict(list)
        for t in trades:
            if t.get("rs_score") is not None:
                rs_groups[rs_bucket(t["rs_score"])].append(t)
        for b in ["Q1 (niedrigste RS)", "Q2", "Q3", "Q4 (höchste RS)"]:
            g = rs_groups.get(b, [])
            if g:
                by_rs[b] = {
                    "n": len(g),
                    "avg_perf_1m": _avg([x["perf_1m"] for x in g]),
                    "hit_rate": _hit_rate([x["perf_1m"] for x in g]),
                    "avg_vs_spy": _avg([x.get("vs_spy_1m") for x in g]),
                }

    # ── 4. Verlust/Gewinn-Asymmetrie + Tail ────────────────────────────────────
    wins = [p for p in perfs if p > 0]
    losses = [p for p in perfs if p <= 0]
    asym = {
        "avg_win": _avg(wins),
        "avg_loss": _avg(losses),
        "win_loss_ratio": round(abs(_avg(wins) / _avg(losses)), 2) if (wins and losses and _avg(losses)) else None,
        "pct_losers_worse_10": round(sum(1 for p in perfs if p < -10) / len(perfs) * 100, 1),
        "pct_winners_better_10": round(sum(1 for p in perfs if p > 10) / len(perfs) * 100, 1),
        "worst_trade": round(min(perfs), 2),
        "best_trade": round(max(perfs), 2),
    }

    # ── 5. SPY-Schlagkraft: Trade-Ebene + Korb-Ebene (pro Datum) ───────────────
    per_date = defaultdict(list)
    for t in trades:
        if t.get("vs_spy_1m") is not None:
            per_date[t["date"]].append(t["vs_spy_1m"])
    date_basket_vs_spy = [_avg(v) for v in per_date.values() if v]
    spy_skill = {
        "pct_trades_beat_spy": round(sum(1 for v in vs_spy if v > 0) / len(vs_spy) * 100, 1) if vs_spy else None,
        "pct_dates_basket_beat_spy": round(sum(1 for v in date_basket_vs_spy if v > 0) / len(date_basket_vs_spy) * 100, 1) if date_basket_vs_spy else None,
        "n_dates": len(date_basket_vs_spy),
    }

    # ── 6. Verteilung ──────────────────────────────────────────────────────────
    dist = _percentiles(perfs)

    # ── 7. Schlechteste Trades ─────────────────────────────────────────────────
    worst = sorted(trades, key=lambda x: x["perf_1m"])[:10]
    worst_trades = [
        {"date": t["date"], "ticker": t["ticker"], "perf_1m": t["perf_1m"],
         "tech_score": t.get("tech_score"), "rs_score": round(t.get("rs_score", 0), 1)}
        for t in worst
    ]

    return {
        "n_trades": len(trades),
        "overall": {
            "avg_perf_1m": _avg(perfs),
            "hit_rate_1m": _hit_rate(perfs),
            "avg_vs_spy_1m": _avg(vs_spy),
            "sharpe_1m": _sharpe(perfs),
            "median_1m": dist[50],
        },
        "by_year": by_year,
        "by_tech_score": by_tech,
        "by_rs_score": by_rs,
        "asymmetry": asym,
        "spy_skill": spy_skill,
        "distribution_pctiles": dist,
        "worst_trades": worst_trades,
    }


def load_and_analyze(path: str = None) -> dict:
    p = path or _RESULTS_FILE
    with open(p, "r", encoding="utf-8") as f:
        return analyze(json.load(f))


def print_report(diag: dict):
    """Druckt einen menschenlesbaren Diagnose-Report."""
    if "error" in diag:
        print("FEHLER:", diag["error"])
        return
    o = diag["overall"]
    print(f"\n{'='*64}\nGESAMT ({diag['n_trades']} messbare Trades)\n{'='*64}")
    print(f"  Ø Return 1M:   {o['avg_perf_1m']:+.2f}%   Median: {o['median_1m']:+.2f}%")
    print(f"  Trefferquote:  {o['hit_rate_1m']:.1f}%")
    print(f"  Ø vs SPY 1M:   {o['avg_vs_spy_1m']:+.2f}%")
    print(f"  Sharpe 1M:     {o['sharpe_1m']}")

    print(f"\n{'─'*64}\nNACH JAHR (Regime-Abhängigkeit)\n{'─'*64}")
    print(f"  {'Jahr':6} {'n':>5} {'ØRet':>8} {'Hit%':>7} {'vsSPY':>8} {'Sharpe':>7}")
    for yr, s in diag["by_year"].items():
        print(f"  {yr:6} {s['n']:>5} {s['avg_perf_1m']:>+8.2f} {s['hit_rate']:>6.1f}% {s['avg_vs_spy']:>+8.2f} {str(s['sharpe']):>7}")

    print(f"\n{'─'*64}\nNACH TECH-SCORE (hat Gate 3 Vorhersagekraft?)\n{'─'*64}")
    print(f"  {'Score':14} {'n':>6} {'ØRet':>8} {'Hit%':>7} {'vsSPY':>8}")
    for b, s in diag["by_tech_score"].items():
        print(f"  {b:14} {s['n']:>6} {s['avg_perf_1m']:>+8.2f} {s['hit_rate']:>6.1f}% {s['avg_vs_spy']:>+8.2f}")

    print(f"\n{'─'*64}\nNACH RS-SCORE-QUARTIL (hat Gate 2 Vorhersagekraft?)\n{'─'*64}")
    print(f"  {'Quartil':22} {'n':>6} {'ØRet':>8} {'Hit%':>7} {'vsSPY':>8}")
    for b, s in diag["by_rs_score"].items():
        print(f"  {b:22} {s['n']:>6} {s['avg_perf_1m']:>+8.2f} {s['hit_rate']:>6.1f}% {s['avg_vs_spy']:>+8.2f}")

    a = diag["asymmetry"]
    print(f"\n{'─'*64}\nGEWINN/VERLUST-ASYMMETRIE & TAIL\n{'─'*64}")
    print(f"  Ø Gewinn: {a['avg_win']:+.2f}%   Ø Verlust: {a['avg_loss']:+.2f}%   Ratio: {a['win_loss_ratio']}")
    print(f"  Verlierer < -10%: {a['pct_losers_worse_10']}%   Gewinner > +10%: {a['pct_winners_better_10']}%")
    print(f"  Bester: {a['best_trade']:+.1f}%   Schlechtester: {a['worst_trade']:+.1f}%")

    s = diag["spy_skill"]
    print(f"\n{'─'*64}\nSPY-SCHLAGKRAFT\n{'─'*64}")
    print(f"  Einzeltrades schlagen SPY: {s['pct_trades_beat_spy']}%")
    print(f"  Körbe (pro Datum) schlagen SPY: {s['pct_dates_basket_beat_spy']}%  (n={s['n_dates']} Dates)")

    d = diag["distribution_pctiles"]
    print(f"\n{'─'*64}\nVERTEILUNG 1M-Return (Perzentile)\n{'─'*64}")
    print(f"  p5={d[5]}%  p25={d[25]}%  p50={d[50]}%  p75={d[75]}%  p95={d[95]}%")

    print(f"\n{'─'*64}\n10 SCHLECHTESTE TRADES\n{'─'*64}")
    for t in diag["worst_trades"]:
        print(f"  {t['date']} {t['ticker']:6} {t['perf_1m']:+7.1f}%  tech={t['tech_score']} rs={t['rs_score']}")


if __name__ == "__main__":
    print_report(load_and_analyze())
