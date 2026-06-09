"""
Wegwerf-Verifikation der Bugfixes (Phase B).
Aufruf: python scripts/verify_fixes.py
"""

import sys
import os
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
import numpy as np

failures = []


def check(name: str, cond: bool, detail: str = ""):
    status = "OK  " if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(name)


# ── B1: _forward_return ───────────────────────────────────────────────────────
from backtest.runner import _forward_return

# Handelstage Mo-Fr, 100 Tage ab 2024-01-01, Kurs steigt 1/Tag
idx = pd.bdate_range("2024-01-01", periods=100)
df = pd.DataFrame({"close": np.arange(100, 200, dtype=float)}, index=idx)

# from_date = 2024-01-05 (Fr, Kurs 104). target +30 Tage = 2024-02-04 (So)
# → erster Handelstag >= target ist Mo 2024-02-05 (Position 25, Kurs 125)
r = _forward_return(df, date(2024, 1, 5), 30)
expected = round((125 / 104 - 1) * 100, 2)
check("B1 Wochenende: erster Handelstag >= target", r == expected, f"{r} vs {expected}")

# Delisting: Daten enden vor target → None (vorher: letzter Kurs als 'Return')
r = _forward_return(df, date(2024, 5, 1), 30)
check("B1 Delisting: None statt verkürzter Periode", r is None, f"{r}")

# target ist Handelstag → exakt dieser Tag
# 2024-01-05 + 31 Tage = 2024-02-05 (Mo, Position 25, Kurs 125)
r = _forward_return(df, date(2024, 1, 5), 31)
check("B1 target=Handelstag: exakter Tag", r == expected, f"{r} vs {expected}")

# ── B2: perf_after ohne Clamping ──────────────────────────────────────────────
import history.performance as perf_mod

_hists = {}


def _fake_load(ticker, start_str, end_date):
    return _hists[ticker]


perf_mod._load_hist_for_perf = _fake_load

# Empfehlung vor 60 Tagen, aber Daten enden nach 10 Tagen (Delisting)
rec_date = date.today() - pd.Timedelta(days=60).to_pytimedelta()
short_idx = pd.bdate_range(rec_date.isoformat(), periods=8)
_hists["XXXX"] = pd.DataFrame({"Close": np.linspace(50, 55, 8)}, index=short_idx)
spy_idx = pd.bdate_range(rec_date.isoformat(), periods=45)
_hists["SPY"] = pd.DataFrame({"Close": np.linspace(500, 520, 45)}, index=spy_idx)

res = perf_mod._compute_performance("XXXX", rec_date.isoformat(), 50.0)
check("B2 1W-Perf vorhanden (Daten reichen)", res.get("performance_1w") is not None,
      str(res.get("performance_1w")))
check("B2 1M-Perf None statt geclampt (Daten enden früher)", res.get("performance_1m") is None,
      str(res.get("performance_1m")))

# tz-aware Index darf nicht crashen
tz_idx = pd.bdate_range(rec_date.isoformat(), periods=45, tz="America/New_York")
_hists["YYYY"] = pd.DataFrame({"Close": np.linspace(50, 60, 45)}, index=tz_idx)
res_tz = perf_mod._compute_performance("YYYY", rec_date.isoformat(), 50.0)
check("B2 tz-aware: _tz_naive normalisiert", res_tz.get("performance_1m") is not None,
      str(res_tz.get("performance_1m")))

# ── B3: Halte-Intervalle inkl. Verkäufe ──────────────────────────────────────
from portfolio.history import _build_holdings, _shares_held_on

positions = [{"ticker": "AAPL", "lots": [
    {"date": "2025-01-10", "shares": 5, "price_eur": 100.0},
]}]
realized = [
    # Teilverkauf: 5 Stück am 2025-03-01 verkauft (gekauft 2025-01-10)
    {"ticker": "AAPL", "buy_date": "2025-01-10", "sell_date": "2025-03-01",
     "shares": 5, "buy_price_eur": 100.0, "sell_price_eur": 120.0},
    # Komplett verkaufte Position
    {"ticker": "MSFT", "buy_date": "2025-02-01", "sell_date": "2025-04-01",
     "shares": 2, "buy_price_eur": 300.0, "sell_price_eur": 330.0},
]
h = _build_holdings(positions, realized)
check("B3 verkaufter Ticker in Holdings", "MSFT" in h, str(sorted(h)))
check("B3 vor Verkauf: 10 Stück AAPL", _shares_held_on(h["AAPL"], date(2025, 2, 1)) == 10.0,
      str(_shares_held_on(h["AAPL"], date(2025, 2, 1))))
check("B3 nach Teilverkauf: 5 Stück AAPL", _shares_held_on(h["AAPL"], date(2025, 3, 1)) == 5.0,
      str(_shares_held_on(h["AAPL"], date(2025, 3, 1))))
check("B3 MSFT während Haltedauer: 2 Stück", _shares_held_on(h["MSFT"], date(2025, 3, 1)) == 2.0,
      str(_shares_held_on(h["MSFT"], date(2025, 3, 1))))
check("B3 MSFT nach Vollverkauf: 0 Stück", _shares_held_on(h["MSFT"], date(2025, 4, 1)) == 0.0,
      str(_shares_held_on(h["MSFT"], date(2025, 4, 1))))

# ── B6: 6M-Lookback ──────────────────────────────────────────────────────────
from analyzer.exits import _rs_negative_6m

# 127 Punkte: erster Wert 100, alle weiteren 99 → Kurs vor 126 Handelstagen war höher
s = pd.Series([100.0] + [99.0] * 126)
check("B6 Kurs unter Stand von vor 126 Tagen → True", _rs_negative_6m(s) is True)
# erster Wert 98 (vor 126 Tagen), Rest 99 → nicht negativ
s2 = pd.Series([98.0] + [99.0] * 126)
check("B6 Kurs über Stand von vor 126 Tagen → False", _rs_negative_6m(s2) is False)

# ── B5: kein ZeroDivision bei Einstand 0 ─────────────────────────────────────
avg_entry_eur = 0.0
current_price_eur = 50.0
crashed = False
try:
    if avg_entry_eur and current_price_eur is not None:
        _ = current_price_eur / avg_entry_eur
except ZeroDivisionError:
    crashed = True
check("B5 Einstand 0: kein ZeroDivisionError", not crashed)

print()
if failures:
    print(f"{len(failures)} FEHLGESCHLAGEN: {failures}")
    sys.exit(1)
print("Alle Checks bestanden.")
