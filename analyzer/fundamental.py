"""
Gate 4 — Fundamentalanalyse
Score muss >= config.FUNDAMENTAL["min_score"] sein (Standard: 60%).
"""

import logging
from config import FUNDAMENTAL

logger = logging.getLogger(__name__)


def check_fundamental(info: dict) -> dict:
    """
    info: yfinance Ticker.info Dictionary

    Gibt zurück:
    {
        "passed": bool,
        "score": float,      # 0.0 – 1.0
        "signals": dict,     # Details zu jedem Signal
        "metrics": dict,     # Rohdaten für Anzeige
    }
    """
    result = {
        "passed": False,
        "score": 0.0,
        "signals": {},
        "metrics": {},
    }

    if not info:
        return result

    try:
        pe = info.get("trailingPE")
        rev_growth = info.get("revenueGrowth")
        profit_margin = info.get("profitMargins")
        debt_equity = info.get("debtToEquity")
        free_cf = info.get("freeCashflow")
        market_cap = info.get("marketCap")
        sector = info.get("sector", "N/A")
        name = info.get("longName", info.get("shortName", ""))

        sig_pe = (pe is not None) and (0 < pe < FUNDAMENTAL["pe_max"])
        sig_growth = (rev_growth is not None) and (rev_growth >= FUNDAMENTAL["revenue_growth_min"])
        sig_margin = (profit_margin is not None) and (profit_margin >= FUNDAMENTAL["profit_margin_min"])
        sig_debt = (debt_equity is not None) and (debt_equity < FUNDAMENTAL["debt_to_equity_max"])
        sig_fcf = (free_cf is not None) and (free_cf > 0)

        signals = {
            f"KGV < {FUNDAMENTAL['pe_max']}": sig_pe,
            f"Umsatzwachstum > {FUNDAMENTAL['revenue_growth_min']*100:.0f}%": sig_growth,
            f"Gewinnmarge > {FUNDAMENTAL['profit_margin_min']*100:.0f}%": sig_margin,
            f"Verschuldung < {FUNDAMENTAL['debt_to_equity_max']}": sig_debt,
            "Free Cashflow positiv": sig_fcf,
        }

        score = sum(signals.values()) / len(signals)

        result["signals"] = signals
        result["score"] = round(score, 3)
        result["passed"] = score >= FUNDAMENTAL["min_score"]
        result["metrics"] = {
            "name": name,
            "sector": sector,
            "pe": round(pe, 1) if pe else None,
            "revenue_growth": f"{rev_growth*100:.1f}%" if rev_growth is not None else "N/A",
            "profit_margin": f"{profit_margin*100:.1f}%" if profit_margin is not None else "N/A",
            "debt_to_equity": round(debt_equity, 1) if debt_equity is not None else None,
            "free_cashflow": _fmt_large(free_cf),
            "market_cap": _fmt_large(market_cap),
        }

    except Exception as e:
        logger.warning(f"Fundamentalanalyse fehlgeschlagen: {e}")

    return result


def _fmt_large(value) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1e12:
        return f"${value/1e12:.2f}T"
    if abs(value) >= 1e9:
        return f"${value/1e9:.2f}B"
    if abs(value) >= 1e6:
        return f"${value/1e6:.2f}M"
    return f"${value:,.0f}"
