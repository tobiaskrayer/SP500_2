"""
Historischer Backtest: simuliert Gates 1+2+3 (Markt, Relative Stärke, Technik)
über historische Kursdaten.

WICHTIG: Fundamentaldaten (Gate 4) können nicht historisch backtested werden —
yfinance liefert nur aktuelle Kennzahlen, keine historischen Snapshots.
Der Backtest testet ausschließlich die technisch-momentum-basierte Komponente.
"""

import itertools
import json
import logging
import os
import pickle
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from analyzer.indicators import rsi_series as _rsi_series

logger = logging.getLogger(__name__)

_BACKTEST_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest")
_RESULTS_FILE = os.path.join(_BACKTEST_CACHE_DIR, "results.json")
_SWEEP_RESULTS_FILE = os.path.join(_BACKTEST_CACHE_DIR, "sweep_results.json")
_PRICE_CACHE_DIR = os.path.join(_BACKTEST_CACHE_DIR, "prices")
_PRICE_CACHE_MAX_AGE_DAYS = 7
_OVERRIDES_FILE = os.path.join(os.path.dirname(__file__), "param_overrides.json")

_DEFAULT_GRID = {
    "min_score":          [0.67, 0.83, 1.0],
    "rsi_min":            [40, 45, 50],
    "rsi_max":            [65, 70, 75],
    "volume_factor":      [1.0, 1.2, 1.5],
    "rs_top_percentile":  [0.20, 0.25, 0.33],
    "rs_min_6m":          [0.0, 3.0],
}

try:
    from config import RELATIVE_STRENGTH, TECHNICAL
    _RS_TOP_PCT = RELATIVE_STRENGTH.get("rs_top_percentile", 0.33)
    _RS_MIN_6M = RELATIVE_STRENGTH.get("rs_min_6m", 0.0)
    _TECH_MIN = TECHNICAL.get("min_score", 0.70)
    _RSI_MIN = TECHNICAL.get("rsi_min", 45)
    _RSI_MAX = TECHNICAL.get("rsi_max", 70)
    _VOL_FACTOR = TECHNICAL.get("volume_factor", 1.2)
    _BB_UPPER_PCT = TECHNICAL.get("bb_upper_pct", 0.95)
except ImportError:
    _RS_TOP_PCT, _RS_MIN_6M, _TECH_MIN = 0.33, 0.0, 0.70
    _RSI_MIN, _RSI_MAX, _VOL_FACTOR = 45, 70, 1.2
    _BB_UPPER_PCT = 0.95


# ── Preis-Cache (per Ticker) ─────────────────────────────────────────────────

def _cache_path(ticker: str) -> str:
    os.makedirs(_PRICE_CACHE_DIR, exist_ok=True)
    return os.path.join(_PRICE_CACHE_DIR, f"{ticker}.pkl")


def _cache_load(ticker: str) -> pd.DataFrame | None:
    p = _cache_path(ticker)
    if not os.path.exists(p):
        return None
    if (time.time() - os.path.getmtime(p)) > _PRICE_CACHE_MAX_AGE_DAYS * 86400:
        return None
    try:
        with open(p, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_save(ticker: str, df: pd.DataFrame):
    try:
        with open(_cache_path(ticker), "wb") as f:
            pickle.dump(df, f)
    except Exception as e:
        logger.debug(f"Backtest-Cache Schreib-Fehler {ticker}: {e}")


def _download_prices(tickers: list[str], years: int, progress_callback=None) -> dict[str, pd.DataFrame]:
    """Lädt OHLCV für alle Ticker — nutzt Tages-Cache um Wiederholungen zu vermeiden."""
    cached = {}
    to_download = []

    for t in tickers:
        df = _cache_load(t)
        if df is not None and len(df) >= 200:
            cached[t] = df
        else:
            to_download.append(t)

    if to_download:
        logger.info(f"Backtest: Lade {len(to_download)} Ticker (Cache: {len(cached)})...")
        period = f"{years + 1}y"
        batch_size = 200
        batches = [to_download[i:i + batch_size] for i in range(0, len(to_download), batch_size)]
        for idx, batch in enumerate(batches):
            if progress_callback:
                progress_callback("download", idx * batch_size, len(to_download), f"Batch {idx+1}/{len(batches)}")
            try:
                raw = yf.download(
                    batch, period=period, auto_adjust=True,
                    progress=False, group_by="ticker", threads=False,
                )
                for ticker in batch:
                    try:
                        df = raw[ticker].copy() if len(batch) > 1 else raw.copy()
                        df = df.dropna(how="all")
                        if len(df) >= 100:
                            _cache_save(ticker, df)
                            cached[ticker] = df
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Backtest-Download Batch {idx+1}: {e}")
            if idx < len(batches) - 1:
                time.sleep(2)

    return cached


# ── Indikator-Vorberechnung ─────────────────────────────────────────────────

def _precompute(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet die Gate-2/3-Indikatoren als komplette Zeitreihe.
    Nutzt exakt dieselben Definitionen wie der Live-Scan (analyzer/technical.py):
      - RSI: Wilder-Glättung (analyzer.indicators.rsi_series)
      - Volumen: 5-Tage- vs. 20-Tage-Schnitt
      - Bollinger-Schwelle: TECHNICAL["bb_upper_pct"] aus config (nicht hartkodiert)
    Der tech_score wird pro Parameter-Satz via _tech_score_from_row abgeleitet.
    """
    close = hist["Close"]
    vol = hist.get("Volume", pd.Series(dtype=float))

    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    # RSI: Wilder-Glättung — identisch zum Live-Scan
    rsi = _rsi_series(close)

    # MACD: Histogramm > 0  ⟺  macd_line > signal_line
    macd_line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_bull = macd_line > signal_line

    # Bollinger: Schwelle aus config statt hartkodiert
    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_lower = bb_ma - 2 * bb_std
    bb_upper = bb_ma + 2 * bb_std
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    bb_pct = (close - bb_lower) / bb_range
    bb_ok = bb_pct < _BB_UPPER_PCT

    # Volumen: 5-Tage-Schnitt vs. 20-Tage-Schnitt — wie Live-Scan
    if len(vol):
        vol_recent = vol.rolling(5).mean()
        vol_avg = vol.rolling(20).mean()
        vol_ratio = (vol_recent / vol_avg.replace(0, np.nan)).replace([np.inf, -np.inf], 0).fillna(0)
    else:
        vol_ratio = pd.Series(0.0, index=close.index)

    return pd.DataFrame({
        "close": close,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma50": close > ma50,
        "above_ma200": close > ma200,
        "rsi": rsi,
        "macd_bull": macd_bull,
        "bb_ok": bb_ok,
        "vol_ratio": vol_ratio,
    }, index=hist.index)


def _tech_score_from_row(row, rsi_min: float, rsi_max: float, vol_factor: float) -> float | None:
    """Berechnet tech_score für eine einzelne Zeile mit variablen Schwellenwerten."""
    try:
        rsi = float(row.get("rsi", float("nan")))
        if pd.isna(rsi):
            return None
        rsi_ok = rsi_min <= rsi <= rsi_max
        # >= wie der Live-Scan (vol_recent >= vol_avg * factor)
        vol_ok = float(row.get("vol_ratio", 0) or 0) >= vol_factor
        return (
            float(bool(row.get("above_ma50", False)))
            + float(bool(row.get("above_ma200", False)))
            + float(rsi_ok)
            + float(bool(row.get("macd_bull", False)))
            + float(bool(row.get("bb_ok", False)))
            + float(vol_ok)
        ) / 6.0
    except Exception:
        return None


# ── Hilfs-Funktionen ─────────────────────────────────────────────────────────

def _slice_to_date(series_or_df, dt: date):
    """Schneidet eine Pandas-Series/DataFrame bis einschließlich dt ab."""
    dt_str = str(dt)
    try:
        idx = series_or_df.index
        if hasattr(idx, "tz") and idx.tz is not None:
            mask = idx.normalize().tz_localize(None) <= pd.Timestamp(dt_str)
        else:
            mask = idx.normalize() <= pd.Timestamp(dt_str)
        return series_or_df[mask]
    except Exception:
        return series_or_df[series_or_df.index <= dt_str]


def _return_since(close_slice: pd.Series, days: int) -> float | None:
    """Return über die letzten `days` Handelstage (off-by-one-korrigiert)."""
    needed = days + 1
    if len(close_slice) < needed:
        return None
    try:
        return float(close_slice.iloc[-1] / close_slice.iloc[-(days + 1)] - 1) * 100
    except Exception:
        return None


def _forward_return(indicator_df: pd.DataFrame, from_date: date, days: int) -> float | None:
    """Kursrendite `days` Kalendertage nach from_date."""
    try:
        target = from_date + timedelta(days=days)
        # Exit = erster Handelstag >= target (max. 5 Tage Toleranz für Wochenende/Feiertage).
        # Vorher wurde der LETZTE Kurs bis target+5 genommen — die Haltedauer war damit
        # systematisch bis zu 5 Tage zu lang und bei Datenende (Delisting) beliebig kurz.
        pos = len(_slice_to_date(indicator_df, target - timedelta(days=1)))
        within_tolerance = len(_slice_to_date(indicator_df, target + timedelta(days=5)))
        if pos >= within_tolerance:
            return None
        entry_row = _slice_to_date(indicator_df, from_date)
        if len(entry_row) < 1:
            return None
        entry_price = float(entry_row["close"].iloc[-1])
        exit_price = float(indicator_df["close"].iloc[pos])
        return round((exit_price / entry_price - 1) * 100, 2)
    except Exception:
        return None


# ── Gemeinsames Setup ─────────────────────────────────────────────────────────

def _build_precomputed(years: int, step_weeks: int,
                       progress_callback=None) -> tuple[dict, object, list, list]:
    """
    Lädt + precomputed alle Ticker einmalig.
    Gibt (precomputed, spy_ind, bt_dates, universe) zurück.
    Bei Fehler enthält precomputed/spy_ind None-Werte.
    """
    os.makedirs(_BACKTEST_CACHE_DIR, exist_ok=True)

    end_date = date.today() - timedelta(days=35)
    start_date = end_date - timedelta(days=365 * years)

    bt_dates = []
    d = start_date
    while d <= end_date:
        bt_dates.append(d)
        d += timedelta(weeks=step_weeks)

    try:
        from analyzer.universe import get_sp500_tickers
        universe = get_sp500_tickers()
    except Exception:
        logger.warning("Tickerliste nicht verfügbar")
        return {}, None, bt_dates, []

    all_tickers = universe + ["SPY"]
    hist_raw = _download_prices(all_tickers, years, progress_callback)

    spy_raw = hist_raw.get("SPY")
    if spy_raw is None or len(spy_raw) < 200:
        logger.error("SPY-Daten fehlen")
        return {}, None, bt_dates, universe

    total_tickers = len(hist_raw)
    precomputed: dict[str, pd.DataFrame] = {}
    for i, (ticker, df) in enumerate(hist_raw.items()):
        if progress_callback and i % 50 == 0:
            progress_callback("precompute", i, total_tickers, ticker)
        try:
            precomputed[ticker] = _precompute(df)
        except Exception:
            pass

    spy_ind = precomputed.get("SPY")
    return precomputed, spy_ind, bt_dates, universe


# ── Simulations-Kern ─────────────────────────────────────────────────────────

def _simulate(precomputed: dict, spy_ind: pd.DataFrame,
              bt_dates: list, params: dict, universe: list | None = None) -> tuple[list, int, int]:
    """
    Führt Gate-1/2/3-Check für alle bt_dates durch.
    Gibt (trades, dates_simulated, dates_skipped_bearish) zurück.
    """
    min_score     = params.get("min_score",          _TECH_MIN)
    rsi_min       = params.get("rsi_min",            _RSI_MIN)
    rsi_max       = params.get("rsi_max",            _RSI_MAX)
    vol_factor    = params.get("volume_factor",      _VOL_FACTOR)
    rs_top_pct    = params.get("rs_top_percentile",  _RS_TOP_PCT)
    rs_min_6m     = params.get("rs_min_6m",          _RS_MIN_6M)

    _universe = universe if universe is not None else [t for t in precomputed if t != "SPY"]

    trades = []
    dates_simulated = 0
    dates_skipped = 0

    for bt_date in bt_dates:
        spy_slice = _slice_to_date(spy_ind, bt_date)
        if len(spy_slice) < 200:
            dates_skipped += 1
            continue
        spy_row = spy_slice.iloc[-1]
        if not (spy_row["above_ma50"] and spy_row["above_ma200"]):
            dates_skipped += 1
            continue

        spy_close_slice = spy_slice["close"]
        sp_ret_3m = _return_since(spy_close_slice, 63)
        sp_ret_6m = _return_since(spy_close_slice, 126)
        if sp_ret_3m is None or sp_ret_6m is None:
            dates_skipped += 1
            continue

        dates_simulated += 1
        candidates = []

        for ticker in _universe:
            ind = precomputed.get(ticker)
            if ind is None:
                continue
            ind_slice = _slice_to_date(ind, bt_date)
            if len(ind_slice) < 200:
                continue
            row = ind_slice.iloc[-1]

            tech_score = _tech_score_from_row(row, rsi_min, rsi_max, vol_factor)
            if tech_score is None or tech_score < min_score:
                continue

            close_slice = ind_slice["close"]
            ret_3m = _return_since(close_slice, 63)
            ret_6m = _return_since(close_slice, 126)
            if ret_3m is None or ret_6m is None:
                continue

            rs_3m = ret_3m - sp_ret_3m
            rs_6m_val = ret_6m - sp_ret_6m

            candidates.append({
                "ticker":     ticker,
                "price":      float(row["close"]),
                "rs_score":   rs_3m + rs_6m_val,
                "rs_6m":      rs_6m_val,
                "tech_score": tech_score,
            })

        if not candidates:
            continue

        cutoff = float(np.percentile([c["rs_score"] for c in candidates],
                                      (1 - rs_top_pct) * 100))
        recommended = [c for c in candidates
                       if c["rs_score"] >= cutoff and c["rs_6m"] >= rs_min_6m]

        if not recommended:
            continue

        spy_perf_1m = _forward_return(spy_ind, bt_date, 30)
        spy_perf_3m = _forward_return(spy_ind, bt_date, 90)

        for c in recommended:
            ind = precomputed.get(c["ticker"])
            if ind is None:
                continue
            p1m = _forward_return(ind, bt_date, 30)
            p3m = _forward_return(ind, bt_date, 90)
            trades.append({
                "date":        str(bt_date),
                "ticker":      c["ticker"],
                "entry_price": c["price"],
                "tech_score":  c["tech_score"],
                "rs_score":    c["rs_score"],
                "rs_6m":       c["rs_6m"],
                "perf_1m":     p1m,
                "perf_3m":     p3m,
                "spy_1m":      spy_perf_1m,
                "spy_3m":      spy_perf_3m,
                "vs_spy_1m":   round(p1m - spy_perf_1m, 2) if (p1m is not None and spy_perf_1m is not None) else None,
                "hit_1m":      p1m > 0 if p1m is not None else None,
                "hit_3m":      p3m > 0 if p3m is not None else None,
            })

    return trades, dates_simulated, dates_skipped


# ── Haupt-Backtest ────────────────────────────────────────────────────────────

def run_backtest(years: int = 2, step_weeks: int = 2, progress_callback=None) -> dict:
    """
    Simuliert den wöchentlichen Scan über die letzten `years` Jahre.

    Backtested: Gate 1 (Marktfilter), Gate 2 (Relative Stärke), Gate 3 (Technik).
    Nicht backtested: Gate 4 (Fundamentaldaten — keine historischen yfinance-Snapshots).

    progress_callback: callable(phase, current, total, info)
      phase: "download" | "precompute" | "simulate"
    """
    precomputed, spy_ind, bt_dates, universe = _build_precomputed(years, step_weeks, progress_callback)

    if spy_ind is None:
        logger.error("SPY-Indikator fehlt — Backtest abgebrochen")
        return _empty_result(years, step_weeks)

    logger.info(f"Backtest: {len(bt_dates)} Simulationsdaten ({years} Jahre)")

    if progress_callback:
        progress_callback("simulate", 0, len(bt_dates), "Starte Simulation...")

    default_params = {
        "min_score":         _TECH_MIN,
        "rsi_min":           _RSI_MIN,
        "rsi_max":           _RSI_MAX,
        "volume_factor":     _VOL_FACTOR,
        "rs_top_percentile": _RS_TOP_PCT,
        "rs_min_6m":         _RS_MIN_6M,
    }

    trades, dates_simulated, dates_skipped = _simulate(
        precomputed, spy_ind, bt_dates, default_params, universe
    )

    result = _compute_stats(trades, dates_simulated, dates_skipped, years, step_weeks)
    _save_results(result)
    return result


# ── Custom-Backtest (Spielwiese) ──────────────────────────────────────────────

def run_custom_backtest(years: int = 2, step_weeks: int = 2,
                        params: dict | None = None,
                        progress_callback=None) -> dict:
    """
    Einzelner Backtest-Lauf mit benutzerdefinierten Parametern.
    Nutzt denselben Preis-Cache wie run_backtest — nach dem ersten
    Download also sehr schnell.
    """
    precomputed, spy_ind, bt_dates, universe = _build_precomputed(years, step_weeks, progress_callback)

    if spy_ind is None:
        return _empty_result(years, step_weeks)

    _params = {
        "min_score":         _TECH_MIN,
        "rsi_min":           _RSI_MIN,
        "rsi_max":           _RSI_MAX,
        "volume_factor":     _VOL_FACTOR,
        "rs_top_percentile": _RS_TOP_PCT,
        "rs_min_6m":         _RS_MIN_6M,
        **(params or {}),
    }

    trades, dates_simulated, dates_skipped = _simulate(
        precomputed, spy_ind, bt_dates, _params, universe
    )
    return _compute_stats(trades, dates_simulated, dates_skipped, years, step_weeks)


# ── Parameter-Sweep ───────────────────────────────────────────────────────────

def run_param_sweep(years: int = 3, step_weeks: int = 2,
                    grid: dict | None = None,
                    objective: str = "avg_vs_spy_1m",
                    train_frac: float = 0.6,
                    min_trades: int = 30,
                    progress_callback=None) -> dict:
    """
    Grid-Search über Gate-2/3-Parameter.

    Optimiert auf der älteren `train_frac` der Zeitreihe, validiert auf
    der neueren (Train/Test-Split gegen Overfitting).

    Gibt zurück: ranked Kombinationen, bestes Ergebnis, Ist-Konfiguration.
    """
    precomputed, spy_ind, bt_dates, universe = _build_precomputed(years, step_weeks, progress_callback)

    if spy_ind is None:
        return _empty_sweep_result(years, step_weeks, objective)

    logger.info(f"Sweep: {len(bt_dates)} Simulations-Dates über {years} Jahre")

    # Train/Test-Split (chronologisch)
    split_idx = int(len(bt_dates) * train_frac)
    train_dates = bt_dates[:split_idx]
    test_dates = bt_dates[split_idx:]

    # Vorberechnete Date-Daten (einmalig für alle bt_dates — Haupt-Effizienz-Gewinn)
    if progress_callback:
        progress_callback("sweep_precompute", 0, len(bt_dates), "Vorberechnung...")
    date_data = _precompute_date_data(precomputed, spy_ind, bt_dates, universe)

    # Grid aufbauen
    _grid = grid or _DEFAULT_GRID
    keys = list(_grid.keys())
    combos = list(itertools.product(*[_grid[k] for k in keys]))
    total_combos = len(combos)
    logger.info(f"Sweep: {total_combos} Kombinationen, {len(train_dates)} Train / {len(test_dates)} Test")

    current_config = {
        "min_score":         _TECH_MIN,
        "rsi_min":           _RSI_MIN,
        "rsi_max":           _RSI_MAX,
        "volume_factor":     _VOL_FACTOR,
        "rs_top_percentile": _RS_TOP_PCT,
        "rs_min_6m":         _RS_MIN_6M,
    }

    ranked = []
    for ci, combo_vals in enumerate(combos):
        params = dict(zip(keys, combo_vals))
        # Defaults für nicht im Grid enthaltene Keys
        for k, v in current_config.items():
            params.setdefault(k, v)

        if progress_callback and ci % 20 == 0:
            progress_callback("sweep", ci, total_combos, f"Kombi {ci+1}/{total_combos}")

        try:
            train_trades = _simulate_from_cache(date_data, train_dates, params)
            train_stats = _compute_stats(train_trades, len(train_dates), 0, years, step_weeks)

            if (train_stats.get("measurable_1m") or 0) < min_trades:
                continue

            test_trades = _simulate_from_cache(date_data, test_dates, params)
            test_stats = _compute_stats(test_trades, len(test_dates), 0, years, step_weeks)

            train_obj = train_stats.get(objective)
            test_obj = test_stats.get(objective)
            if train_obj is None:
                continue

            overfit_gap = round(train_obj - test_obj, 2) if test_obj is not None else None

            ranked.append({
                **params,
                f"train_{objective}": round(train_obj, 2),
                f"test_{objective}":  round(test_obj, 2) if test_obj is not None else None,
                "overfit_gap":        overfit_gap,
                "train_trades":       train_stats.get("measurable_1m", 0),
                "test_trades":        test_stats.get("measurable_1m", 0),
                "train_hit_1m":       train_stats.get("hit_rate_1m"),
                "test_hit_1m":        test_stats.get("hit_rate_1m"),
                "train_sharpe":       train_stats.get("sharpe_1m"),
                "test_sharpe":        test_stats.get("sharpe_1m"),
            })
        except Exception as e:
            logger.debug(f"Sweep Kombi {ci}: {e}")

    ranked.sort(key=lambda x: x.get(f"train_{objective}") or float("-inf"), reverse=True)
    best = {k: v for k, v in ranked[0].items() if k in current_config} if ranked else None

    if progress_callback:
        progress_callback("sweep", total_combos, total_combos, "Abgeschlossen")

    result = {
        "computed_at":        datetime.now().isoformat(),
        "years":              years,
        "step_weeks":         step_weeks,
        "objective":          objective,
        "train_frac":         train_frac,
        "total_combos_tested": len(combos),
        "valid_combos":       len(ranked),
        "current_config":     current_config,
        "best":               best,
        "ranked":             ranked[:50],
    }
    _save_sweep_results(result)
    return result


def _precompute_date_data(precomputed: dict, spy_ind: pd.DataFrame,
                           bt_dates: list, universe: list) -> dict:
    """
    Precomputed alle date-spezifischen Daten (Slices, RS-Returns, Forward-Returns)
    einmalig für alle Daten. Der Combo-Loop greift nur noch auf diesen Cache zu
    (O(1) Lookups statt teurer Slice-Operationen pro Kombination).
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

        spy_close_slice = spy_slice["close"]
        sp_ret_3m = _return_since(spy_close_slice, 63)
        sp_ret_6m = _return_since(spy_close_slice, 126)
        if sp_ret_3m is None or sp_ret_6m is None:
            result[bt_date] = None
            continue

        spy_perf_1m = _forward_return(spy_ind, bt_date, 30)
        spy_perf_3m = _forward_return(spy_ind, bt_date, 90)

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

            rs_3m = ret_3m - sp_ret_3m
            rs_6m_val = ret_6m - sp_ret_6m

            ticker_data[ticker] = {
                "row":       row,
                "price":     float(row["close"]),
                "rs_score":  rs_3m + rs_6m_val,
                "rs_6m":     rs_6m_val,
                "p1m":       _forward_return(ind, bt_date, 30),
                "p3m":       _forward_return(ind, bt_date, 90),
            }

        result[bt_date] = {
            "ticker_data":  ticker_data,
            "spy_perf_1m":  spy_perf_1m,
            "spy_perf_3m":  spy_perf_3m,
        }

    return result


def _simulate_from_cache(date_data: dict, bt_dates: list, params: dict) -> list:
    """
    Schnelle Simulation über vorberechnete Date-Daten (für den Sweep).
    Recomputed nur tech_score und RS-Filter (beides billig).
    """
    min_score  = params.get("min_score",          _TECH_MIN)
    rsi_min    = params.get("rsi_min",            _RSI_MIN)
    rsi_max    = params.get("rsi_max",            _RSI_MAX)
    vol_factor = params.get("volume_factor",      _VOL_FACTOR)
    rs_top_pct = params.get("rs_top_percentile",  _RS_TOP_PCT)
    rs_min_6m  = params.get("rs_min_6m",          _RS_MIN_6M)

    trades = []
    for bt_date in bt_dates:
        dd = date_data.get(bt_date)
        if dd is None:
            continue

        candidates = []
        for ticker, td in dd["ticker_data"].items():
            tech_score = _tech_score_from_row(td["row"], rsi_min, rsi_max, vol_factor)
            if tech_score is None or tech_score < min_score:
                continue
            candidates.append({
                "ticker":     ticker,
                "price":      td["price"],
                "rs_score":   td["rs_score"],
                "rs_6m":      td["rs_6m"],
                "tech_score": tech_score,
                "p1m":        td["p1m"],
                "p3m":        td["p3m"],
            })

        if not candidates:
            continue

        cutoff = float(np.percentile([c["rs_score"] for c in candidates],
                                      (1 - rs_top_pct) * 100))
        recommended = [c for c in candidates
                       if c["rs_score"] >= cutoff and c["rs_6m"] >= rs_min_6m]
        if not recommended:
            continue

        spy_perf_1m = dd["spy_perf_1m"]
        spy_perf_3m = dd["spy_perf_3m"]

        for c in recommended:
            p1m = c["p1m"]
            p3m = c["p3m"]
            trades.append({
                "date":        str(bt_date),
                "ticker":      c["ticker"],
                "entry_price": c["price"],
                "tech_score":  c["tech_score"],
                "rs_score":    c["rs_score"],
                "rs_6m":       c["rs_6m"],
                "perf_1m":     p1m,
                "perf_3m":     p3m,
                "spy_1m":      spy_perf_1m,
                "spy_3m":      spy_perf_3m,
                "vs_spy_1m":   round(p1m - spy_perf_1m, 2) if (p1m is not None and spy_perf_1m is not None) else None,
                "hit_1m":      p1m > 0 if p1m is not None else None,
                "hit_3m":      p3m > 0 if p3m is not None else None,
            })

    return trades


# ── Overrides ─────────────────────────────────────────────────────────────────

def apply_overrides(params: dict):
    """
    Schreibt Parameter-Overrides in backtest/param_overrides.json.
    config.py liest diese Datei beim nächsten Import und merged die Werte
    in TECHNICAL / RELATIVE_STRENGTH.
    """
    os.makedirs(os.path.dirname(os.path.abspath(_OVERRIDES_FILE)), exist_ok=True)
    with open(_OVERRIDES_FILE, "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    logger.info(f"Parameter-Overrides gespeichert: {params}")


def load_overrides() -> dict:
    """Gibt aktuell aktive Overrides zurück (leeres Dict wenn keine vorhanden)."""
    if not os.path.exists(_OVERRIDES_FILE):
        return {}
    try:
        with open(_OVERRIDES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def clear_overrides():
    """Entfernt param_overrides.json — stellt config-Defaults wieder her."""
    if os.path.exists(_OVERRIDES_FILE):
        os.remove(_OVERRIDES_FILE)
        logger.info("Parameter-Overrides entfernt — config.py-Defaults wiederhergestellt")


# ── Statistiken ───────────────────────────────────────────────────────────────

def _compute_stats(trades: list[dict], dates_simulated: int, dates_skipped: int,
                   years: int, step_weeks: int) -> dict:
    t1m = [t for t in trades if t.get("perf_1m") is not None]
    t3m = [t for t in trades if t.get("perf_3m") is not None]

    def _avg(lst, key):
        vals = [x[key] for x in lst if x.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _hit_rate(lst, key):
        relevant = [x for x in lst if x.get(key) is not None]
        return round(sum(1 for x in relevant if x[key]) / len(relevant) * 100, 1) if relevant else None

    def _sharpe(lst, key):
        vals = [x[key] for x in lst if x.get(key) is not None]
        if len(vals) < 5:
            return None
        arr = np.array(vals)
        return round(float(arr.mean() / arr.std()), 2) if arr.std() > 0 else None

    def _max_dd(lst, key):
        vals = [x[key] for x in lst if x.get(key) is not None]
        return round(min(vals), 2) if vals else None

    monthly: dict[str, list] = {}
    for t in t1m:
        ym = t["date"][:7]
        monthly.setdefault(ym, []).append(t)
    by_month = []
    for ym in sorted(monthly.keys()):
        grp = monthly[ym]
        by_month.append({
            "month":       ym,
            "n":           len(grp),
            "avg_perf_1m": _avg(grp, "perf_1m"),
            "hit_rate":    _hit_rate(grp, "hit_1m"),
            "avg_vs_spy":  _avg(grp, "vs_spy_1m"),
        })

    return {
        "computed_at":           datetime.now().isoformat(),
        "years":                 years,
        "step_weeks":            step_weeks,
        "dates_simulated":       dates_simulated,
        "dates_skipped_bearish": dates_skipped,
        "total_trades":          len(trades),
        "measurable_1m":         len(t1m),
        "measurable_3m":         len(t3m),
        "hit_rate_1m":           _hit_rate(t1m, "hit_1m"),
        "avg_return_1m":         _avg(t1m, "perf_1m"),
        "avg_vs_spy_1m":         _avg(t1m, "vs_spy_1m"),
        "sharpe_1m":             _sharpe(t1m, "perf_1m"),
        "max_drawdown_1m":       _max_dd(t1m, "perf_1m"),
        "hit_rate_3m":           _hit_rate(t3m, "hit_3m"),
        "avg_return_3m":         _avg(t3m, "perf_3m"),
        "by_month":              by_month,
        "trades":                trades,
    }


def _empty_result(years: int, step_weeks: int) -> dict:
    return {
        "computed_at": datetime.now().isoformat(),
        "years": years, "step_weeks": step_weeks,
        "dates_simulated": 0, "dates_skipped_bearish": 0,
        "total_trades": 0, "measurable_1m": 0, "measurable_3m": 0,
        "hit_rate_1m": None, "avg_return_1m": None,
        "avg_vs_spy_1m": None, "sharpe_1m": None, "max_drawdown_1m": None,
        "hit_rate_3m": None, "avg_return_3m": None,
        "by_month": [], "trades": [],
    }


def _empty_sweep_result(years: int, step_weeks: int, objective: str) -> dict:
    return {
        "computed_at": datetime.now().isoformat(),
        "years": years, "step_weeks": step_weeks, "objective": objective,
        "train_frac": 0.6, "total_combos_tested": 0, "valid_combos": 0,
        "current_config": {}, "best": None, "ranked": [],
    }


# ── Persistenz ────────────────────────────────────────────────────────────────

def load_cached_results() -> dict | None:
    if not os.path.exists(_RESULTS_FILE):
        return None
    try:
        with open(_RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_results(result: dict):
    os.makedirs(_BACKTEST_CACHE_DIR, exist_ok=True)
    try:
        with open(_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Backtest-Ergebnisse konnten nicht gespeichert werden: {e}")


def load_sweep_results() -> dict | None:
    if not os.path.exists(_SWEEP_RESULTS_FILE):
        return None
    try:
        with open(_SWEEP_RESULTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_sweep_results(result: dict):
    os.makedirs(_BACKTEST_CACHE_DIR, exist_ok=True)
    try:
        with open(_SWEEP_RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Sweep-Ergebnisse konnten nicht gespeichert werden: {e}")
