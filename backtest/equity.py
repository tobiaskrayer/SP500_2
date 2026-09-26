"""Cash-constrained next-open simulation with fixed holding period.

Separate from overlapping signal-return diagnostics. No inferred historical
fundamentals or sectors, and no discretionary stop execution.
"""
import numpy as np
import pandas as pd
from config import BACKTEST, PORTFOLIO_RISK


def simulate_equity(prices, signals, start, end, *, initial_cash=10000.0,
                    holding_days=None, position_cap=None, cost_bps=None):
    holding_days = BACKTEST["holding_days"] if holding_days is None else holding_days
    position_cap = PORTFOLIO_RISK["max_position_weight"] if position_cap is None else position_cap
    cost = ((BACKTEST["cost_bps_per_side"] + BACKTEST["slippage_bps_per_side"])
            if cost_bps is None else cost_bps) / 10000
    if not (initial_cash > 0 and holding_days > 0 and 0 < position_cap <= 1 and 0 <= cost < 1):
        raise ValueError("Invalid execution assumptions")
    frames = {}
    for tk, df in prices.items():
        df = df.copy()
        df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
        frames[tk] = df[~df.index.duplicated(keep="last")]
    benchmark = frames["SPY"]
    dates = benchmark.loc[str(start):str(end)].index
    scheduled = {}
    for signal in signals:
        pos = dates.searchsorted(pd.Timestamp(signal["date"]), side="right")
        if pos < len(dates) and (dates[pos] - pd.Timestamp(signal["date"])).days <= 5:
            scheduled.setdefault(dates[pos], {})[signal["ticker"]] = signal
    cash, active, curve, trades = initial_cash, {}, [], []
    missing_marks = 0
    def price(tk, dt, field):
        df = frames.get(tk)
        if df is None or dt not in df.index or field not in df:
            return None
        value = float(df.at[dt, field])
        return value if np.isfinite(value) and value > 0 else None
    for dt in dates:
        # All exits at the opening auction precede new purchases.
        for tk, lot in list(active.items()):
            opening = price(tk, dt, "open")
            if opening is not None and dt >= lot["due"]:
                proceeds = lot["shares"] * opening * (1-cost)
                cash += proceeds
                trades.append({"ticker": tk, "entry_date": str(lot["entry"].date()),
                               "exit_date": str(dt.date()), "return_pct": (proceeds/lot["spent"]-1)*100})
                del active[tk]
        nav = cash + sum(lot["shares"] * (price(tk, dt, "open") or lot["last"]) for tk, lot in active.items())
        candidates = [(tk, price(tk, dt, "open")) for tk in sorted(scheduled.get(dt, {})) if tk not in active]
        candidates = [(tk, px) for tk, px in candidates if px is not None]
        budget = min(cash / len(candidates), nav * position_cap) if candidates else 0
        for tk, opening in candidates:
            if budget <= 0:
                continue
            shares = budget / (opening * (1+cost))
            cash -= budget
            active[tk] = {"shares": shares, "last": opening, "entry": dt,
                          "due": dt + pd.Timedelta(days=holding_days), "spent": budget}
        for tk, lot in active.items():
            closing = price(tk, dt, "close")
            if closing is None:
                missing_marks += 1
            else:
                lot["last"] = closing
        nav = cash + sum(lot["shares"] * lot["last"] for lot in active.values())
        curve.append({"date": str(dt.date()), "equity": nav, "cash": cash, "positions": len(active)})
    if not curve:
        return {"curve": [], "trades": [], "max_drawdown_pct": None, "sharpe": None}
    values = pd.Series([initial_cash] + [r["equity"] for r in curve])
    daily = values.pct_change().dropna()
    dd = (values / values.cummax() - 1).min() * 100
    sharpe = float(daily.mean()/daily.std(ddof=1)*np.sqrt(252)) if len(daily) > 1 and daily.std(ddof=1) > 0 else None
    first, last = price("SPY", dates[0], "open"), price("SPY", dates[-1], "close")
    return {"curve": curve, "trades": trades, "return_pct": (values.iloc[-1]/initial_cash-1)*100,
            "max_drawdown_pct": float(dd), "sharpe": sharpe,
            "benchmark_return_pct": (last*(1-cost)/(first*(1+cost))-1)*100 if first and last else None,
            "open_positions": len(active), "missing_marks": missing_marks,
            "assumptions": {"holding_days": holding_days, "cost_bps_per_side": cost*10000,
                            "max_position_weight": position_cap, "cash_interest": 0},
            "limitations": ["Heutiges Universum", "Keine historischen Fundamentals/Sektorgrenzen",
                            "Feste Haltedauer; keine automatischen Stops", "Offene Positionen zum letzten Kurs bewertet",
                            "Fehlende Kurse werden fortgeschrieben; Delistings nicht modelliert"]}
