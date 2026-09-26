"""Equal allocation constrained by existing positions and sector exposure."""
import math
from config import PORTFOLIO_RISK


def _sector(value):
    return "Unbekannt" if not value or value in ("N/A", "—", "Unknown") else value


def allocate(candidates, cash, holdings=(), *, position_cap=None, sector_cap=None):
    position_cap = PORTFOLIO_RISK["max_position_weight"] if position_cap is None else position_cap
    sector_cap = PORTFOLIO_RISK["max_sector_weight"] if sector_cap is None else sector_cap
    if not math.isfinite(cash) or cash < 0 or not 0 < position_cap <= 1 or not 0 < sector_cap <= 1:
        raise ValueError("Ungültige Allokationsgrenzen")
    holdings = list(holdings)
    if any(not math.isfinite(h["value"]) or h["value"] < 0 for h in holdings):
        raise ValueError("Ungültiger Positionswert")
    total = cash + sum(h["value"] for h in holdings)
    by_ticker, by_sector = {}, {}
    for h in holdings:
        by_ticker[h["ticker"]] = by_ticker.get(h["ticker"], 0) + h["value"]
        sector = _sector(h.get("sector"))
        by_sector[sector] = by_sector.get(sector, 0) + h["value"]
    unique = {c["ticker"]: c for c in candidates}
    output = {ticker: 0.0 for ticker in unique}
    desired = cash / len(unique) if unique else 0
    # Sector scaling treats all members equally rather than favouring input order.
    provisional = {tk: min(desired, max(0, total * position_cap - by_ticker.get(tk, 0))) for tk in unique}
    sectors = {}
    for tk, c in unique.items():
        sectors.setdefault(_sector(c.get("sector")), []).append(tk)
    for sector, tickers in sectors.items():
        budget = max(0, total * sector_cap - by_sector.get(sector, 0))
        wanted = sum(provisional[tk] for tk in tickers)
        scale = min(1, budget / wanted) if wanted else 0
        for tk in tickers:
            output[tk] = math.floor(provisional[tk] * scale * 100) / 100
    return {"positions": output, "cash_remaining": round(cash - sum(output.values()), 2), "total_equity": total}
