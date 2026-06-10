"""
Stop-Loss-Simulation: misst den Tail-Effekt der Live-Exit-Logik im Backtest.

Bisher hielt der Backtest jeden Trade stur bis zum Horizont (1M/3M) — die
ATR-Stops des Live-Systems (analyzer/exits.py) waren nicht modelliert, das
Verlust-Tail (-50 % Einzeltrades) damit unbeantwortet. Dieses Modul simuliert
je Trade den täglichen OHLC-Pfad aus dem Preis-Cache:

  Stop:    Entry − atr_stop_multiplier × ATR(14)   (config.EXITS, live: 2.0)
  Target:  Entry + atr_target_multiplier × ATR(14) (live: 3.0)
  ATR-Cap: min(ATR, 6 % vom Kurs) — wie exits.py (Spike-Schutz)

Gap-Handling wie eine echte Stop-Order: eröffnet der Tag unter dem Stop,
wird zum Open gefüllt (nicht zum Stop-Preis). Varianten:

  hold      — Halten bis Horizont (Baseline = bisheriger Backtest)
  stop      — fixer ATR-Stop, sonst Horizont-Exit
  stop+tp   — Stop und Take-Profit
  trailing  — Stop folgt dem höchsten Close seit Entry (Abstand 2×ATR)

Auswahl: v2 Top-10 (Live-Logik) über die angereicherten 10-Jahres-Daten.

Ausführen:  python -X utf8 -m backtest.stop_sim
"""

import os
import pickle
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from backtest.compare import get_date_data, _select_v2, PARAMS_V2
from backtest.runner import _PRICE_CACHE_DIR
from config import EXITS

logger = logging.getLogger(__name__)

_STOP_MULT = EXITS.get("atr_stop_multiplier", 2.0)
_TP_MULT = EXITS.get("atr_target_multiplier", 3.0)
_ATR_CAP_PCT = 0.06   # wie analyzer/exits.py: ATR für Stop-Berechnung auf 6 % gekappt


def _load_ohlc(ticker: str) -> pd.DataFrame | None:
    """Lädt den rohen OHLC-Frame aus dem Backtest-Preis-Cache (tz-naiv)."""
    p = os.path.join(_PRICE_CACHE_DIR, f"{ticker}.pkl")
    if not os.path.exists(p):
        return None
    try:
        with open(p, "rb") as f:
            df = pickle.load(f)
        if getattr(df.index, "tz", None) is not None:
            df = df.copy()
            df.index = df.index.tz_localize(None)
        df.index = df.index.normalize()
        return df
    except Exception:
        return None


def _atr14(df_slice: pd.DataFrame) -> float | None:
    """ATR(14) mit Rolling-Mean — identisch zu analyzer/indicators.atr()."""
    if len(df_slice) < 15:
        return None
    high, low, close = df_slice["High"], df_slice["Low"], df_slice["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(14).mean().iloc[-1]
    return float(val) if not pd.isna(val) else None


def simulate_trade(ohlc: pd.DataFrame, entry_date: date, horizon_days: int,
                   mode: str, stop_mult: float = _STOP_MULT, tp_mult: float = _TP_MULT,
                   atr_cap_pct: float | None = _ATR_CAP_PCT) -> dict | None:
    """
    Simuliert einen Trade ab entry_date über horizon_days Kalendertage.
    mode: "hold" | "stop" | "stop+tp" | "trailing"
    Gibt {"ret_pct", "days_held", "exit_reason"} zurück oder None (keine Daten).
    """
    entry_ts = pd.Timestamp(entry_date)
    past = ohlc[ohlc.index <= entry_ts]
    if len(past) < 15:
        return None
    entry_price = float(past["Close"].iloc[-1])
    if not np.isfinite(entry_price) or entry_price <= 0:
        return None

    atr = _atr14(past)
    if atr is None:
        return None
    if atr_cap_pct is not None:
        atr = min(atr, entry_price * atr_cap_pct)
    stop = entry_price - stop_mult * atr
    target = entry_price + tp_mult * atr

    # Horizont-Exit: erster Handelstag >= entry + horizon (max. 5 Tage Toleranz),
    # konsistent mit runner._forward_return.
    target_ts = pd.Timestamp(entry_date + timedelta(days=horizon_days))
    future = ohlc[(ohlc.index > entry_ts) & (ohlc.index <= target_ts + pd.Timedelta(days=5))]
    if future.empty or future.index[-1] < target_ts:
        return None
    horizon_pos = int(np.searchsorted(future.index.values, target_ts.to_datetime64()))

    highest_close = entry_price
    for i in range(horizon_pos + 1):
        row = future.iloc[i]
        o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])
        if not all(np.isfinite(v) for v in (o, h, l, c)):
            continue

        if mode in ("stop", "stop+tp"):
            if o <= stop:   # Gap unter den Stop → Fill zum Open
                return {"ret_pct": (o / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "stop_gap"}
            if l <= stop:
                return {"ret_pct": (stop / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "stop"}
        if mode == "stop+tp":
            if o >= target:
                return {"ret_pct": (o / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "tp_gap"}
            if h >= target:
                return {"ret_pct": (target / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "tp"}
        if mode == "trailing":
            tstop = highest_close - stop_mult * atr
            if o <= tstop:
                return {"ret_pct": (o / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "trail_gap"}
            if l <= tstop:
                return {"ret_pct": (tstop / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "trail"}
            highest_close = max(highest_close, c)

        if i == horizon_pos:
            return {"ret_pct": (c / entry_price - 1) * 100, "days_held": i + 1, "exit_reason": "horizon"}

    return None


def run_stop_simulation(years: int = 10, step_weeks: int = 2,
                        configs: list[tuple] | None = None) -> dict:
    """
    Selektiert v2-Top-10-Trades und simuliert alle Konfigurationen.
    configs: Liste (label, horizon_days, mode, stop_mult, tp_mult, atr_cap_pct).
    """
    bt_dates, date_data = get_date_data(years, step_weeks)

    if configs is None:
        configs = [(f"{m} {h}d", h, m, _STOP_MULT, _TP_MULT, _ATR_CAP_PCT)
                   for h in (30, 56) for m in ("hold", "stop", "stop+tp", "trailing")]

    # Trade-Liste: (date, ticker)
    picks = []
    for bt_date in bt_dates:
        dd = date_data.get(bt_date)
        if dd is None:
            continue
        for tk, _td in _select_v2(dd["ticker_data"], PARAMS_V2):
            picks.append((bt_date, tk))

    ohlc_cache: dict[str, pd.DataFrame | None] = {}
    results: dict[str, list] = {label: [] for (label, *_rest) in configs}

    for bt_date, tk in picks:
        if tk not in ohlc_cache:
            ohlc_cache[tk] = _load_ohlc(tk)
        ohlc = ohlc_cache[tk]
        if ohlc is None:
            continue
        for label, h, m, sm, tm, cap in configs:
            r = simulate_trade(ohlc, bt_date, h, m, stop_mult=sm, tp_mult=tm, atr_cap_pct=cap)
            if r is not None:
                results[label].append(r)

    return {"n_picks": len(picks), "results": results}


def _stats(trades: list) -> dict | None:
    if len(trades) < 50:
        return None
    arr = np.array([t["ret_pct"] for t in trades])
    stopped = sum(1 for t in trades if t["exit_reason"] != "horizon")
    return {
        "n": len(arr),
        "ret": round(float(arr.mean()), 2),
        "median": round(float(np.median(arr)), 2),
        "hit": round(float((arr > 0).mean() * 100), 1),
        "sharpe": round(float(arr.mean() / arr.std()), 3) if arr.std() > 0 else None,
        "p5": round(float(np.percentile(arr, 5)), 1),
        "worst": round(float(arr.min()), 1),
        "stopped_pct": round(stopped / len(arr) * 100, 1),
        "avg_days": round(float(np.mean([t["days_held"] for t in trades])), 1),
    }


def print_report(sim: dict):
    print(f"\nStop-Simulation auf v2 Top-10 ({sim['n_picks']} Picks)\n")
    header = (f"{'Variante':30} {'n':>6} {'ØRet':>7} {'Median':>7} {'Hit%':>6} "
              f"{'Sharpe':>7} {'p5':>7} {'Worst':>7} {'Stop%':>6} {'ØTage':>6}")
    print(header)
    print("-" * len(header))
    for label, trades in sim["results"].items():
        s = _stats(trades)
        if s is None:
            continue
        print(f"{label:30} {s['n']:>6} {s['ret']:>+7.2f} {s['median']:>+7.2f} {s['hit']:>6.1f} "
              f"{s['sharpe']:>7.3f} {s['p5']:>7.1f} {s['worst']:>7.1f} {s['stopped_pct']:>6.1f} {s['avg_days']:>6.1f}")


if __name__ == "__main__":
    # Hauptvergleich: Live-Konfiguration (2x ATR, 6%-Cap) je Modus + Horizont,
    # danach Stop-Weiten-Sweep (lockerere Stops, ohne Cap) am 56d-Horizont.
    configs = []
    for h in (30, 56):
        configs.append((f"Halten {h}d (Baseline)", h, "hold", _STOP_MULT, _TP_MULT, _ATR_CAP_PCT))
        configs.append((f"Stop 2x+Cap6% {h}d (live)", h, "stop", 2.0, _TP_MULT, 0.06))
        configs.append((f"Stop+TP {h}d (live)", h, "stop+tp", 2.0, 3.0, 0.06))
        configs.append((f"Trailing 2x {h}d (live)", h, "trailing", 2.0, _TP_MULT, 0.06))
    for sm in (3.0, 4.0, 5.0):
        configs.append((f"Stop {sm:.0f}x ohne Cap 56d", 56, "stop", sm, _TP_MULT, None))
        configs.append((f"Trailing {sm:.0f}x ohne Cap 56d", 56, "trailing", sm, _TP_MULT, None))
    print_report(run_stop_simulation(configs=configs))
