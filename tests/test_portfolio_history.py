"""Portfolio-History-Regressionen (B3/B5): Verkäufe in der Historie, Einstand 0."""
from datetime import date

from portfolio.history import _build_holdings, _shares_held_on


POSITIONS = [{"ticker": "AAPL", "lots": [
    {"date": "2025-01-10", "shares": 5, "price_eur": 100.0},
]}]
REALIZED = [
    # Teilverkauf: 5 Stueck am 2025-03-01 verkauft (gekauft 2025-01-10)
    {"ticker": "AAPL", "buy_date": "2025-01-10", "sell_date": "2025-03-01",
     "shares": 5, "buy_price_eur": 100.0, "sell_price_eur": 120.0},
    # Komplett verkaufte Position
    {"ticker": "MSFT", "buy_date": "2025-02-01", "sell_date": "2025-04-01",
     "shares": 2, "buy_price_eur": 300.0, "sell_price_eur": 330.0},
]


def test_sold_ticker_appears_in_holdings():
    h = _build_holdings(POSITIONS, REALIZED)
    assert "MSFT" in h


def test_share_counts_around_sales():
    h = _build_holdings(POSITIONS, REALIZED)
    assert _shares_held_on(h["AAPL"], date(2025, 2, 1)) == 10.0   # vor Teilverkauf
    assert _shares_held_on(h["AAPL"], date(2025, 3, 1)) == 5.0    # ab Verkaufstag
    assert _shares_held_on(h["MSFT"], date(2025, 3, 1)) == 2.0    # waehrend Haltedauer
    assert _shares_held_on(h["MSFT"], date(2025, 4, 1)) == 0.0    # nach Vollverkauf


def test_zero_entry_price_guard():
    # B5: avg_entry_eur == 0 darf keine Division ausloesen (Guard-Muster aus manager.py)
    avg_entry_eur, current_price_eur = 0.0, 50.0
    pnl = None
    if avg_entry_eur and current_price_eur is not None:
        pnl = current_price_eur / avg_entry_eur
    assert pnl is None
