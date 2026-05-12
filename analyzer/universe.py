"""
Lädt die aktuelle S&P500-Tickerliste von Wikipedia.
Fallback: hartcodierte Liste der Top-100-Werte.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def get_sp500_tickers() -> list[str]:
    """Gibt eine Liste aller S&P500-Ticker zurück."""
    return [t for t, _ in _fetch_sp500_table()]


def get_sp500_names() -> dict[str, str]:
    """Gibt ein Dict {Ticker: Firmenname} für alle S&P500-Titel zurück."""
    return {t: n for t, n in _fetch_sp500_table()}


def _fetch_sp500_table() -> list[tuple[str, str]]:
    """Lädt Ticker + Firmennamen von Wikipedia. Fallback auf hartcodierte Liste."""
    try:
        tables = pd.read_html(SP500_WIKI_URL)
        df = tables[0]
        result = []
        for _, row in df.iterrows():
            ticker = str(row["Symbol"]).replace(".", "-")
            name = str(row.get("Security", row.get("Company", ticker)))
            result.append((ticker, name))
        logger.info(f"S&P500-Tabelle geladen: {len(result)} Titel")
        return result
    except Exception as e:
        logger.warning(f"Wikipedia-Abruf fehlgeschlagen: {e} — nutze Fallback-Liste")
        return [(t, t) for t in _fallback_tickers()]


def _fallback_tickers() -> list[str]:
    """Fallback: Top-100 S&P500-Titel nach Marktkapitalisierung."""
    return [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "BRK-B",
        "AVGO", "JPM", "LLY", "V", "UNH", "XOM", "MA", "JNJ", "PG", "HD",
        "COST", "MRK", "ABBV", "CVX", "KO", "BAC", "CRM", "NFLX", "AMD",
        "PEP", "TMO", "ORCL", "ACN", "ADBE", "WMT", "MCD", "ABT", "PM",
        "DHR", "CSCO", "GE", "TXN", "NEE", "CAT", "VZ", "AMGN", "IBM",
        "MS", "RTX", "INTC", "HON", "INTU", "UPS", "GS", "QCOM", "SPGI",
        "BKNG", "LOW", "ELV", "T", "AXP", "AMAT", "ISRG", "PLD", "DE",
        "TJX", "MDT", "BLK", "GILD", "SYK", "VRTX", "ADI", "REGN", "MMC",
        "CI", "MO", "ZTS", "LRCX", "PGR", "PANW", "SO", "DUK", "ICE",
        "BSX", "CME", "AON", "CL", "HCA", "MCO", "WM", "NOC", "ETN",
        "EMR", "ITW", "FI", "APH", "GD", "ROP", "ADP", "NSC", "KLAC",
    ]
