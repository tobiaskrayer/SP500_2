"""
Haupt-Analyse-Engine:
Lädt alle S&P500-Aktien, führt alle 4 Gates durch und gibt
eine Liste der empfohlenen Aktien zurück.
"""

import yfinance as yf
import pandas as pd
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from analyzer.universe import get_sp500_tickers
from analyzer.market_filter import check_market
from analyzer.relative_strength import check_relative_strength
from analyzer.technical import check_technical
from analyzer.fundamental import check_fundamental
from config import ANALYSIS

logger = logging.getLogger(__name__)


def run_full_scan(progress_callback=None) -> dict:
    """
    Führt den vollständigen Scan aller S&P500-Aktien durch.

    progress_callback: optional callable(current, total, ticker) für Fortschrittsanzeige

    Gibt zurück:
    {
        "timestamp": str,
        "market": dict,         # Gate-1-Ergebnis
        "recommendations": list,  # Aktien, die alle Gates bestanden
        "all_results": list,    # Alle Aktien mit Gate-Ergebnissen
        "scan_duration_s": float,
    }
    """
    start = time.time()
    timestamp = datetime.now().isoformat()

    # Gate 1: Marktcheck
    market = check_market()

    all_results = []
    recommendations = []

    if not market["passed"]:
        logger.info(f"Gate 1 nicht bestanden: {market['reason']} — Scan übersprungen")
        return {
            "timestamp": timestamp,
            "market": market,
            "recommendations": [],
            "all_results": [],
            "scan_duration_s": round(time.time() - start, 1),
        }

    # S&P500-Tickerliste
    tickers = get_sp500_tickers()
    total = len(tickers)
    logger.info(f"Starte Scan für {total} Titel...")

    # S&P500-Kursdaten für relative Stärke
    sp500_hist = _get_sp500_history()

    # Parallele Analyse
    results = []
    with ThreadPoolExecutor(max_workers=ANALYSIS["max_workers"]) as executor:
        futures = {
            executor.submit(_analyze_ticker, ticker, sp500_hist): ticker
            for ticker in tickers
        }
        done = 0
        for future in as_completed(futures):
            ticker = futures[future]
            done += 1
            try:
                res = future.result()
                if res:
                    results.append(res)
            except Exception as e:
                logger.warning(f"{ticker}: {e}")
            if progress_callback:
                progress_callback(done, total, ticker)

    # Sortierung: Empfehlungen zuerst, dann nach Tech-Score
    results.sort(key=lambda x: (not x["recommended"], -x["tech_score"]))
    all_results = results
    recommendations = [r for r in results if r["recommended"]]

    logger.info(f"Scan abgeschlossen: {len(recommendations)} Empfehlungen aus {len(results)} analysierten Titeln")

    return {
        "timestamp": timestamp,
        "market": market,
        "recommendations": recommendations,
        "all_results": all_results,
        "scan_duration_s": round(time.time() - start, 1),
    }


def _get_sp500_history() -> pd.Series:
    try:
        sp = yf.Ticker("^GSPC")
        hist = sp.history(period="1y")
        return hist["Close"]
    except Exception as e:
        logger.error(f"S&P500-History-Fehler: {e}")
        return pd.Series(dtype=float)


def _analyze_ticker(ticker: str, sp500_hist: pd.Series) -> dict | None:
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1y")
        if hist is None or len(hist) < 60:
            return None

        close = hist["Close"]

        # Gate 2: Relative Stärke
        rs = check_relative_strength(close, sp500_hist)

        # Gate 3: Technische Analyse
        tech = check_technical(hist)

        # Gate 4: Fundamentalanalyse
        try:
            info = stock.info
        except Exception:
            info = {}
        fund = check_fundamental(info)

        recommended = rs["passed"] and tech["passed"] and fund["passed"]

        return {
            "ticker": ticker,
            "name": fund["metrics"].get("name", ticker),
            "sector": fund["metrics"].get("sector", "N/A"),
            "recommended": recommended,
            # Gate-Ergebnisse
            "gate_rs": rs["passed"],
            "gate_tech": tech["passed"],
            "gate_fund": fund["passed"],
            # Scores
            "tech_score": tech["score"],
            "fund_score": fund["score"],
            # Detail-Daten (für Report)
            "rs": rs,
            "tech": tech,
            "fund": fund,
            "price": tech["indicators"].get("price") if tech["indicators"] else None,
            "hist": hist,
        }

    except Exception as e:
        logger.debug(f"{ticker} übersprungen: {e}")
        return None
