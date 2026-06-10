"""
A/B-Vergleich zweier Empfehlungs-Strategien auf identischen historischen Daten.

v1 = aktuelle Live-Logik (Gate 1 Markt + Gate 3 Tech-Score-Schwelle + Gate 2 RS-Perzentil top 33%).
v2 = datengetrieben optimiert anhand der 10-Jahres-Diagnose:

  Befund 1: Tech-Score rankt nicht (6/6 schlechter als 5/6) → v2 nutzt Trend-/
            Überkauft-Filter strukturell als HARTE Bedingung statt einer Score-Schwelle,
            und belohnt "alle 6 Signale" nicht mehr.
  Befund 2: Edge lebt im obersten RS-Quartil → v2 verschärft den RS-Schnitt (top 20 %).
  Befund 3: Tail-Risiko durch parabolische/hochvolatile Namen → v2 fügt einen
            Volatilitäts-Deckel (annualisierte 20T-Vola) und einen Anti-Parabel-Filter
            (extrem hohe RS gekappt) hinzu.

Beide Strategien laufen über dieselben Simulationsdaten und denselben Marktfilter
(Gate 1), damit nur die Titelauswahl verglichen wird. Reine Auswertung über den
vorhandenen Preis-Cache — kein erneuter Download nötig, wenn results.json frisch ist.
"""

import logging
import os
import pickle

import numpy as np
import pandas as pd

from backtest.runner import (
    _build_precomputed, _slice_to_date, _return_since, _forward_return,
    _tech_score_from_row, _compute_stats,
    _RS_TOP_PCT, _RS_MIN_6M, _TECH_MIN, _RSI_MIN, _RSI_MAX, _VOL_FACTOR,
)

logger = logging.getLogger(__name__)

_DD_CACHE = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest", "enriched_dd.pkl")


# Strategie-Parameter — v1 spiegelt die config-Defaults, v2 die optimierten Werte.
PARAMS_V1 = {
    "min_score":         _TECH_MIN,      # 0.70
    "rsi_min":           _RSI_MIN,       # 45
    "rsi_max":           _RSI_MAX,       # 70
    "volume_factor":     _VOL_FACTOR,    # 1.2
    "rs_top_percentile": _RS_TOP_PCT,    # 0.33
    "rs_min_6m":         _RS_MIN_6M,     # 0.0
}

# Finale v2 = Variante H aus der Hebel-Isolation über 10 Jahre.
# Begründung je Parameter:
#   rs_top_percentile 0.20  — Befund 2: Edge lebt im obersten RS-Bereich; strenger = besser
#                             (monoton bis ~15 %), 20 % hält die Streubreite nahe v1.
#   require_full_trend      — Befund 1: Tech-Score-Gradation rankt nicht. Statt einer
#                             Score-Schwelle: Trend (über MA50 UND MA200) als harte Pflicht.
#   require_not_overbought  — RSI ≤ rsi_max und unter oberem BB-Band → keine Tops kaufen.
# Bewusst NICHT enthalten (im Test wirkungslos bis schädlich, Tail blieb -84 %):
#   vol_cap_annual / rs_parabolic_cap — Entry-Filter fangen Gap-/Blowup-Risiko nicht;
#   das ist Aufgabe der Stop-/Exit-Logik (im Backtest nicht modelliert). Daher deaktiviert.
PARAMS_V2 = {
    "rsi_min":            45,
    "rsi_max":            70,
    "volume_factor":      1.2,
    "rs_top_percentile":  0.20,
    "rs_min_6m":          0.0,
    "require_full_trend": True,
    "require_not_overbought": True,
    "vol_cap_annual":     1e9,     # deaktiviert
    "rs_parabolic_cap":   1e9,     # deaktiviert
}


def _build_enriched_date_data(precomputed, spy_ind, bt_dates, universe):
    """
    Wie runner._precompute_date_data, aber zusätzlich mit Trailing-Volatilität pro
    Ticker und ohne jegliche Strategie-Filter — jede Strategie filtert selbst.
    """
    result = {}
    for bt_date in bt_dates:
        spy_slice = _slice_to_date(spy_ind, bt_date)
        if len(spy_slice) < 200:
            result[bt_date] = None
            continue
        spy_row = spy_slice.iloc[-1]
        if not (spy_row["above_ma50"] and spy_row["above_ma200"]):
            result[bt_date] = None
            continue

        spy_close = spy_slice["close"]
        sp_ret_3m = _return_since(spy_close, 63)
        sp_ret_6m = _return_since(spy_close, 126)
        if sp_ret_3m is None or sp_ret_6m is None:
            result[bt_date] = None
            continue

        ticker_data = {}
        for ticker in universe:
            ind = precomputed.get(ticker)
            if ind is None:
                continue
            ind_slice = _slice_to_date(ind, bt_date)
            if len(ind_slice) < 200:
                continue
            row = ind_slice.iloc[-1]
            if pd.isna(row.get("rsi", float("nan"))):
                continue

            close_slice = ind_slice["close"]
            ret_3m = _return_since(close_slice, 63)
            ret_6m = _return_since(close_slice, 126)
            if ret_3m is None or ret_6m is None:
                continue

            # Trailing-Volatilität: annualisierte Std der Tagesrenditen über 20 Handelstage
            daily = close_slice.iloc[-21:].pct_change().dropna()
            vol_annual = float(daily.std() * np.sqrt(252)) if len(daily) >= 10 else None

            ticker_data[ticker] = {
                "row":      row,
                "price":    float(row["close"]),
                "rs_score": ret_3m - sp_ret_3m + ret_6m - sp_ret_6m,
                "rs_6m":    ret_6m - sp_ret_6m,
                "vol":      vol_annual,
                "p1m":      _forward_return(ind, bt_date, 30),
                "p3m":      _forward_return(ind, bt_date, 90),
            }

        result[bt_date] = {
            "ticker_data": ticker_data,
            "spy_perf_1m": _forward_return(spy_ind, bt_date, 30),
            "spy_perf_3m": _forward_return(spy_ind, bt_date, 90),
        }

    return result


def _select_v1(ticker_data: dict, p: dict) -> list:
    """Aktuelle Logik: Tech-Score-Schwelle, dann RS-Perzentil top 33 % unter den Tech-Passern."""
    cands = []
    for tk, td in ticker_data.items():
        ts = _tech_score_from_row(td["row"], p["rsi_min"], p["rsi_max"], p["volume_factor"])
        if ts is None or ts < p["min_score"]:
            continue
        cands.append((tk, td, ts))
    if not cands:
        return []
    cutoff = float(np.percentile([c[1]["rs_score"] for c in cands], (1 - p["rs_top_percentile"]) * 100))
    return [(tk, td) for tk, td, ts in cands
            if td["rs_score"] >= cutoff and td["rs_6m"] >= p["rs_min_6m"]]


def _select_v2(ticker_data: dict, p: dict) -> list:
    """
    Optimierte Logik:
      - Trend Pflicht: über MA50 UND MA200
      - nicht überkauft: RSI ≤ rsi_max UND unter oberem BB-Band
      - Volatilitäts-Deckel + Anti-Parabel-Filter (Tail-Schutz)
      - dann strengeres RS-Perzentil (top 20 %) unter den Survivors
    """
    cands = []
    for tk, td in ticker_data.items():
        row = td["row"]
        if p.get("require_full_trend") and not (row.get("above_ma50") and row.get("above_ma200")):
            continue
        if p.get("require_not_overbought"):
            rsi = float(row.get("rsi", 50))
            if rsi > p["rsi_max"] or not bool(row.get("bb_ok", True)):
                continue
        vol = td.get("vol")
        if vol is not None and vol > p["vol_cap_annual"]:
            continue
        if td["rs_score"] > p["rs_parabolic_cap"]:
            continue
        cands.append((tk, td))
    if not cands:
        return []
    cutoff = float(np.percentile([c[1]["rs_score"] for c in cands], (1 - p["rs_top_percentile"]) * 100))
    return [(tk, td) for tk, td in cands
            if td["rs_score"] >= cutoff and td["rs_6m"] >= p["rs_min_6m"]]


def _simulate_strategy(date_data: dict, bt_dates: list, select_fn, params: dict) -> list:
    """Wendet eine Auswahl-Strategie auf alle Dates an und baut die Trade-Liste."""
    trades = []
    for bt_date in bt_dates:
        dd = date_data.get(bt_date)
        if dd is None:
            continue
        selected = select_fn(dd["ticker_data"], params)
        if not selected:
            continue
        spy_1m, spy_3m = dd["spy_perf_1m"], dd["spy_perf_3m"]
        for tk, td in selected:
            p1m, p3m = td["p1m"], td["p3m"]
            trades.append({
                "date": str(bt_date), "ticker": tk, "entry_price": td["price"],
                "tech_score": _tech_score_from_row(td["row"], params.get("rsi_min", _RSI_MIN),
                                                   params.get("rsi_max", _RSI_MAX),
                                                   params.get("volume_factor", _VOL_FACTOR)),
                "rs_score": td["rs_score"], "rs_6m": td["rs_6m"],
                "perf_1m": p1m, "perf_3m": p3m, "spy_1m": spy_1m, "spy_3m": spy_3m,
                "vs_spy_1m": round(p1m - spy_1m, 2) if (p1m is not None and spy_1m is not None) else None,
                "hit_1m": p1m > 0 if p1m is not None else None,
                "hit_3m": p3m > 0 if p3m is not None else None,
            })
    return trades


def get_date_data(years: int = 10, step_weeks: int = 2, progress_callback=None,
                  use_cache: bool = True):
    """
    Baut die angereicherten Date-Daten (teuer) — oder lädt sie aus dem Pickle-Cache.
    Cache-Key ist implizit (years/step_weeks); bei Änderung use_cache=False setzen.
    """
    if use_cache and os.path.exists(_DD_CACHE):
        try:
            with open(_DD_CACHE, "rb") as f:
                blob = pickle.load(f)
            if (blob.get("years") == years and blob.get("step_weeks") == step_weeks
                    and blob.get("bt_dates") and blob.get("date_data")):
                return blob["bt_dates"], blob["date_data"]
        except Exception:
            pass

    precomputed, spy_ind, bt_dates, universe = _build_precomputed(years, step_weeks, progress_callback)
    if spy_ind is None:
        raise RuntimeError("SPY-Daten fehlen — Vergleich nicht möglich.")
    if progress_callback:
        progress_callback("enrich", 0, len(bt_dates), "Reichere Date-Daten an...")
    date_data = _build_enriched_date_data(precomputed, spy_ind, bt_dates, universe)

    try:
        os.makedirs(os.path.dirname(_DD_CACHE), exist_ok=True)
        with open(_DD_CACHE, "wb") as f:
            pickle.dump({"years": years, "step_weeks": step_weeks,
                         "bt_dates": bt_dates, "date_data": date_data}, f)
    except Exception as e:
        logger.debug(f"DD-Cache Schreibfehler: {e}")

    return bt_dates, date_data


def run_comparison(years: int = 10, step_weeks: int = 2,
                   params_v2: dict = None, progress_callback=None) -> dict:
    """
    Baut Daten einmalig (gecacht) und vergleicht v1 vs v2 über dieselben Dates.
    Gibt {"v1": stats, "v2": stats, "params_v1":..., "params_v2":...} zurück.
    """
    bt_dates, date_data = get_date_data(years, step_weeks, progress_callback)

    p2 = {**PARAMS_V2, **(params_v2 or {})}

    trades_v1 = _simulate_strategy(date_data, bt_dates, _select_v1, PARAMS_V1)
    trades_v2 = _simulate_strategy(date_data, bt_dates, _select_v2, p2)

    return {
        "years": years, "step_weeks": step_weeks,
        "params_v1": PARAMS_V1, "params_v2": p2,
        "v1": _compute_stats(trades_v1, len(bt_dates), 0, years, step_weeks),
        "v2": _compute_stats(trades_v2, len(bt_dates), 0, years, step_weeks),
    }


if __name__ == "__main__":
    import sys
    yrs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    r = run_comparison(years=yrs, step_weeks=2)
    for name in ("v1", "v2"):
        s = r[name]
        print(f"{name}: n={s['measurable_1m']}  vsSPY={s['avg_vs_spy_1m']}%  "
              f"Hit={s['hit_rate_1m']}%  Sharpe={s['sharpe_1m']}  "
              f"Ret1M={s['avg_return_1m']}%  Ret3M={s['avg_return_3m']}%")
