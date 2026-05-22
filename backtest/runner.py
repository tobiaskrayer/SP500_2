"""
Historischer Backtest: simuliert Gates 1+2+3 (Markt, Relative Stärke, Technik)
über historische Kursdaten der letzten 1–3 Jahre.

WICHTIG: Fundamentaldaten (Gate 4) können nicht historisch backtested werden —
yfinance liefert nur aktuelle Kennzahlen, keine historischen Snapshots.
Der Backtest testet ausschließlich die technisch-momentum-basierte Komponente.
"""

import json
import logging
import os
import pickle
import time
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_BACKTEST_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "backtest")
_RESULTS_FILE = os.path.join(_BACKTEST_CACHE_DIR, "results.json")
_PRICE_CACHE_DIR = os.path.join(_BACKTEST_CACHE_DIR, "prices")
_PRICE_CACHE_MAX_AGE_DAYS = 7

try:
    from config import RELATIVE_STRENGTH, TECHNICAL
    _RS_TOP_PCT = RELATIVE_STRENGTH.get("rs_top_percentile", 0.33)
    _RS_MIN_6M = RELATIVE_STRENGTH.get("rs_min_6m", 0.0)
    _TECH_MIN = TECHNICAL.get("min_score", 0.70)
    _RSI_MIN = TECHNICAL.get("rsi_min", 45)
    _RSI_MAX = TECHNICAL.get("rsi_max", 70)
    _VOL_FACTOR = TECHNICAL.get("volume_factor", 1.2)
except ImportError:
    _RS_TOP_PCT, _RS_MIN_6M, _TECH_MIN = 0.33, 0.0, 0.70
    _RSI_MIN, _RSI_MAX, _VOL_FACTOR = 45, 70, 1.2


# ── Preis-Cache (3Y OHLCV, per Ticker) ───────────────────────────────────────

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
    """Lädt 3Y-OHLCV für alle Ticker — nutzt Tages-Cache um Wiederholungen zu vermeiden."""
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


# ── Indikator-Vorberechnung (vektorisiert) ────────────────────────────────────

def _precompute(hist: pd.DataFrame) -> pd.DataFrame:
    """
    Berechnet alle Gate-2/3-Indikatoren als komplette Zeitreihe.
    Gibt DataFrame zurück: eine Zeile pro Handelstag, Spalten = Indikatoren.
    """
    close = hist["Close"]
    vol = hist.get("Volume", pd.Series(dtype=float))
    high = hist.get("High", pd.Series(dtype=float))
    low = hist.get("Low", pd.Series(dtype=float))

    ma50 = close.rolling(50).mean()
    ma200 = close.rolling(200).mean()

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    # MACD: Histogramm > 0 → bullisch
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_bull = (macd_line > signal_line)

    # Bollinger 20d — Kurs < 95% Bandbreite
    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_lower = bb_ma - 2 * bb_std
    bb_upper = bb_ma + 2 * bb_std
    bb_range = (bb_upper - bb_lower).replace(0, np.nan)
    bb_pct = (close - bb_lower) / bb_range
    bb_ok = bb_pct < 0.95

    # Volumen
    vol_avg = vol.rolling(20).mean() if len(vol) else pd.Series(dtype=float)
    vol_elevated = (vol > vol_avg * _VOL_FACTOR) if len(vol_avg) else pd.Series(False, index=close.index)

    above_ma50 = close > ma50
    above_ma200 = close > ma200
    rsi_ok = (rsi >= _RSI_MIN) & (rsi <= _RSI_MAX)

    # Tech-Score: 6 Signale / 6
    tech_score = (
        above_ma50.astype(float)
        + above_ma200.astype(float)
        + rsi_ok.astype(float)
        + macd_bull.astype(float)
        + bb_ok.astype(float)
        + vol_elevated.astype(float)
    ) / 6.0

    return pd.DataFrame({
        "close": close,
        "ma50": ma50,
        "ma200": ma200,
        "above_ma50": above_ma50,
        "above_ma200": above_ma200,
        "rsi": rsi,
        "rsi_ok": rsi_ok,
        "macd_bull": macd_bull,
        "bb_ok": bb_ok,
        "vol_elevated": vol_elevated,
        "tech_score": tech_score,
    }, index=hist.index)


def _slice_to_date(series_or_df, dt: date):
    """Schneidet eine Pandas-Series/DataFrame bis einschließlich dt ab."""
    dt_str = str(dt)
    try:
        # DatetimeIndex mit oder ohne Timezone
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
        future = indicator_df[indicator_df.index > str(from_date)]
        future_until = future[future.index <= str(target + timedelta(days=5))]
        if len(future_until) < 1:
            return None
        entry_row = _slice_to_date(indicator_df, from_date)
        if len(entry_row) < 1:
            return None
        entry_price = float(entry_row["close"].iloc[-1])
        exit_price = float(future_until["close"].iloc[-1])
        return round((exit_price / entry_price - 1) * 100, 2)
    except Exception:
        return None


# ── Haupt-Simulation ──────────────────────────────────────────────────────────

def run_backtest(years: int = 2, step_weeks: int = 2, progress_callback=None) -> dict:
    """
    Simuliert den wöchentlichen Scan über die letzten `years` Jahre.

    Backtested: Gate 1 (Marktfilter), Gate 2 (Relative Stärke), Gate 3 (Technik).
    Nicht backtested: Gate 4 (Fundamentaldaten — keine historischen Snapshots).

    progress_callback: callable(phase, current, total, info)
      phase: "download" | "precompute" | "simulate"

    Gibt zurück:
    {
        "computed_at": str, "years": int, "step_weeks": int,
        "dates_simulated": int, "dates_skipped_bearish": int,
        "total_trades": int,
        "hit_rate_1m": float | None, "avg_return_1m": float | None,
        "avg_vs_spy_1m": float | None, "sharpe_1m": float | None,
        "hit_rate_3m": float | None, "avg_return_3m": float | None,
        "max_drawdown_1m": float | None,
        "by_month": list[dict],
        "by_sector": list[dict],   # leer (kein hist. Sektor verfügbar)
        "trades": list[dict],
    }
    """
    os.makedirs(_BACKTEST_CACHE_DIR, exist_ok=True)

    # Simulationsdaten
    end_date = date.today() - timedelta(days=35)   # 35 Tage Puffer für 1M-Return
    start_date = end_date - timedelta(days=365 * years)

    bt_dates = []
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            bt_dates.append(d)
        d += timedelta(weeks=step_weeks)

    logger.info(f"Backtest: {len(bt_dates)} Simulationsdaten ({start_date} bis {end_date})")

    # Tickerliste
    try:
        from analyzer.universe import get_sp500_tickers
        universe = get_sp500_tickers()
    except Exception:
        logger.warning("Tickerliste nicht verfügbar — Backtest abgebrochen")
        return _empty_result(years, step_weeks)

    all_tickers = universe + ["SPY"]

    # Preise laden
    hist_raw = _download_prices(all_tickers, years, progress_callback)
    spy_raw = hist_raw.get("SPY")
    if spy_raw is None or len(spy_raw) < 200:
        logger.error("SPY-Daten fehlen — Backtest abgebrochen")
        return _empty_result(years, step_weeks)

    # Indikatoren vorberechnen (vektorisiert — einmalig pro Ticker)
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
    if spy_ind is None:
        logger.error("SPY-Indikator fehlen")
        return _empty_result(years, step_weeks)

    # Simulation
    trades = []
    dates_simulated = 0
    dates_skipped = 0

    for sim_i, bt_date in enumerate(bt_dates):
        if progress_callback and sim_i % 5 == 0:
            progress_callback("simulate", sim_i, len(bt_dates), str(bt_date))

        # Gate 1: Marktcheck
        spy_slice = _slice_to_date(spy_ind, bt_date)
        if len(spy_slice) < 200:
            dates_skipped += 1
            continue
        spy_row = spy_slice.iloc[-1]
        if not (spy_row["above_ma50"] and spy_row["above_ma200"]):
            dates_skipped += 1
            continue

        # S&P500-Returns für RS-Berechnung
        spy_close_slice = spy_slice["close"]
        sp_ret_3m = _return_since(spy_close_slice, 63)
        sp_ret_6m = _return_since(spy_close_slice, 126)
        if sp_ret_3m is None or sp_ret_6m is None:
            dates_skipped += 1
            continue

        dates_simulated += 1
        candidates = []

        for ticker in universe:
            ind = precomputed.get(ticker)
            if ind is None:
                continue
            ind_slice = _slice_to_date(ind, bt_date)
            if len(ind_slice) < 200:
                continue
            row = ind_slice.iloc[-1]
            if pd.isna(row["tech_score"]):
                continue

            # Gate 3 vorab
            if float(row["tech_score"]) < _TECH_MIN:
                continue

            # Gate 2: RS
            close_slice = ind_slice["close"]
            ret_3m = _return_since(close_slice, 63)
            ret_6m = _return_since(close_slice, 126)
            if ret_3m is None or ret_6m is None:
                continue

            rs_3m = ret_3m - sp_ret_3m
            rs_6m = ret_6m - sp_ret_6m
            rs_score = rs_3m + rs_6m

            candidates.append({
                "ticker": ticker,
                "price": float(row["close"]),
                "rs_score": rs_score,
                "rs_6m": rs_6m,
                "tech_score": float(row["tech_score"]),
            })

        if not candidates:
            continue

        # RS-Perzentil-Cutoff
        cutoff = float(np.percentile([c["rs_score"] for c in candidates], (1 - _RS_TOP_PCT) * 100))
        recommended = [
            c for c in candidates
            if c["rs_score"] >= cutoff and c["rs_6m"] >= _RS_MIN_6M
        ]

        if not recommended:
            continue

        # Forward-Returns berechnen
        spy_perf_1m = _forward_return(spy_ind, bt_date, 30)
        spy_perf_3m = _forward_return(spy_ind, bt_date, 90)

        for c in recommended:
            ind = precomputed.get(c["ticker"])
            if ind is None:
                continue
            p1m = _forward_return(ind, bt_date, 30)
            p3m = _forward_return(ind, bt_date, 90)
            trades.append({
                "date": str(bt_date),
                "ticker": c["ticker"],
                "entry_price": c["price"],
                "tech_score": c["tech_score"],
                "rs_score": c["rs_score"],
                "rs_6m": c["rs_6m"],
                "perf_1m": p1m,
                "perf_3m": p3m,
                "spy_1m": spy_perf_1m,
                "spy_3m": spy_perf_3m,
                "vs_spy_1m": round(p1m - spy_perf_1m, 2) if (p1m is not None and spy_perf_1m is not None) else None,
                "hit_1m": p1m > 0 if p1m is not None else None,
                "hit_3m": p3m > 0 if p3m is not None else None,
            })

    # Statistiken
    result = _compute_stats(trades, dates_simulated, dates_skipped, years, step_weeks)
    _save_results(result)
    return result


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
        if not vals:
            return None
        return round(min(vals), 2)

    # Nach Monat aggregieren
    monthly: dict[str, list] = {}
    for t in t1m:
        ym = t["date"][:7]
        monthly.setdefault(ym, []).append(t)
    by_month = []
    for ym in sorted(monthly.keys()):
        grp = monthly[ym]
        by_month.append({
            "month": ym,
            "n": len(grp),
            "avg_perf_1m": _avg(grp, "perf_1m"),
            "hit_rate": _hit_rate(grp, "hit_1m"),
            "avg_vs_spy": _avg(grp, "vs_spy_1m"),
        })

    return {
        "computed_at": datetime.now().isoformat(),
        "years": years,
        "step_weeks": step_weeks,
        "dates_simulated": dates_simulated,
        "dates_skipped_bearish": dates_skipped,
        "total_trades": len(trades),
        "measurable_1m": len(t1m),
        "measurable_3m": len(t3m),
        "hit_rate_1m": _hit_rate(t1m, "hit_1m"),
        "avg_return_1m": _avg(t1m, "perf_1m"),
        "avg_vs_spy_1m": _avg(t1m, "vs_spy_1m"),
        "sharpe_1m": _sharpe(t1m, "perf_1m"),
        "max_drawdown_1m": _max_dd(t1m, "perf_1m"),
        "hit_rate_3m": _hit_rate(t3m, "hit_3m"),
        "avg_return_3m": _avg(t3m, "perf_3m"),
        "by_month": by_month,
        "trades": trades,
    }


def _empty_result(years: int, step_weeks: int) -> dict:
    return {
        "computed_at": datetime.now().isoformat(),
        "years": years,
        "step_weeks": step_weeks,
        "dates_simulated": 0,
        "dates_skipped_bearish": 0,
        "total_trades": 0,
        "measurable_1m": 0,
        "measurable_3m": 0,
        "hit_rate_1m": None, "avg_return_1m": None,
        "avg_vs_spy_1m": None, "sharpe_1m": None,
        "max_drawdown_1m": None, "hit_rate_3m": None,
        "avg_return_3m": None,
        "by_month": [],
        "trades": [],
    }


def load_cached_results() -> dict | None:
    """Gibt gecachte Backtest-Ergebnisse zurück, oder None wenn nicht vorhanden."""
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
