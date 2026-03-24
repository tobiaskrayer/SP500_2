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
    try:
        tables = pd.read_html(SP500_WIKI_URL)
        df = tables[0]
        tickers = df["Symbol"].tolist()
        # Wikipedia verwendet manchmal Punkte statt Bindestriche (z.B. BRK.B → BRK-B)
        tickers = [t.replace(".", "-") for t in tickers]
        logger.info(f"S&P500-Tickerliste geladen: {len(tickers)} Titel")
        return tickers
    except Exception as e:
        logger.warning(f"Wikipedia-Abruf fehlgeschlagen: {e} — nutze Fallback-Liste")
        return _fallback_tickers()


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
