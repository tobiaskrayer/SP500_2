"""Versioned, side-effect-free selection shared by scans and simulations."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math

import numpy as np

from config import MARKET, RELATIVE_STRENGTH, TECHNICAL, RECOMMENDER_V2

STRATEGY_VERSION = "2026-09-consistent-v3"


@dataclass(frozen=True)
class SelectionInput:
    ticker: str
    rs_score: float | None
    rs_6m: float | None
    tech_passed: bool
    trend_ok: bool
    not_overbought: bool
    fundamental_passed: bool = True


@dataclass(frozen=True)
class Selection:
    gate_rs: bool = False
    gate_rs_v2: bool = False
    recommended: bool = False
    recommended_v2: bool = False
    v2_rank: int | None = None


def finite(value) -> bool:
    return isinstance(value, (int, float, np.number)) and math.isfinite(value)


def strategy_metadata() -> dict:
    from config import FUNDAMENTAL, EXITS, PORTFOLIO_RISK, BACKTEST
    parameters = {"market": MARKET, "rs": RELATIVE_STRENGTH, "tech": TECHNICAL,
                  "v2": RECOMMENDER_V2, "fundamental": FUNDAMENTAL, "exits": EXITS,
                  "allocation": PORTFOLIO_RISK, "execution": BACKTEST}
    digest = hashlib.sha256(json.dumps(parameters, sort_keys=True).encode()).hexdigest()[:16]
    return {"version": STRATEGY_VERSION, "config_hash": digest,
            "parameters": json.loads(json.dumps(parameters))}


def select(inputs: list[SelectionInput], *, market_passed: bool = True,
           top_pct: float | None = None, top_pct_v2: float | None = None,
           min_6m: float | None = None, top_n: int | None = None) -> dict[str, Selection]:
    """Rank ALL valid RS observations before applying either strategy's gates."""
    top_pct = RELATIVE_STRENGTH["rs_top_percentile"] if top_pct is None else top_pct
    top_pct_v2 = RECOMMENDER_V2["rs_top_percentile"] if top_pct_v2 is None else top_pct_v2
    min_6m = RELATIVE_STRENGTH["rs_min_6m"] if min_6m is None else min_6m
    top_n = RECOMMENDER_V2["top_n"] if top_n is None else top_n
    valid = [x for x in inputs if finite(x.rs_score) and finite(x.rs_6m)]
    output = {x.ticker: Selection() for x in inputs}
    if not valid:
        return output
    scores = [x.rs_score for x in valid]
    cut1, cut2 = (float(np.percentile(scores, (1 - p) * 100)) for p in (top_pct, top_pct_v2))
    survivors = []
    for x in valid:
        g1, g2 = x.rs_score >= cut1 and x.rs_6m >= min_6m, x.rs_score >= cut2 and x.rs_6m >= min_6m
        rec1 = market_passed and g1 and x.tech_passed and x.fundamental_passed
        rec2 = market_passed and g2 and x.trend_ok and x.not_overbought and x.fundamental_passed
        output[x.ticker] = Selection(bool(g1), bool(g2), bool(rec1))
        if rec2:
            survivors.append(x)
    for rank, x in enumerate(sorted(survivors, key=lambda x: (-x.rs_score, x.ticker))[:top_n], 1):
        previous = asdict(output[x.ticker])
        output[x.ticker] = Selection(**{**previous, "recommended_v2": True, "v2_rank": rank})
    return output


def evaluate_market(price, ma50, ma200, vix) -> dict:
    """Same market rules in live and backtest; missing data never imply bullish."""
    complete = all(finite(x) and x > 0 for x in (price, ma50, ma200, vix))
    above50 = finite(price) and finite(ma50) and price > ma50
    above200 = finite(price) and finite(ma200) and price > ma200
    allowed50 = finite(price) and finite(ma50) and price >= ma50 * (1 - MARKET["sp500_below_50ma_pct"])
    allowed200 = finite(price) and finite(ma200) and price >= ma200 * (1 - MARKET["sp500_below_200ma_pct"])
    passed = bool(complete and allowed50 and allowed200 and vix <= MARKET["vix_stop"])
    return {"passed": passed, "warning": bool(passed and vix > MARKET["vix_max"]),
            "data_complete": complete, "sp500_above_ma50": bool(above50),
            "sp500_above_ma200": bool(above200), "ma50_allowed": bool(allowed50),
            "ma200_allowed": bool(allowed200)}
