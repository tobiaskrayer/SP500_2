"""NYSE sessions, including holidays, DST and early closes (no network)."""
from functools import lru_cache

import pandas as pd
import exchange_calendars as xcals


@lru_cache(maxsize=8)
def calendar(year: int):
    return xcals.get_calendar("XNYS", start=f"{year-2}-01-01", end=f"{year+1}-12-31")


def last_completed_session(now=None):
    now = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    schedule = calendar(now.year).schedule
    # Allow 15 minutes for the provider to finalize the daily bar.
    eligible = schedule[schedule["close"] + pd.Timedelta(minutes=15) <= now]
    return eligible.index[-1].date()


def completed_bars(hist, now=None):
    if hist is None or hist.empty:
        return hist
    last = last_completed_session(now)
    return hist.loc[hist.index.date <= last].copy()
