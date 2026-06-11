"""
Lädt die aktuelle S&P500-Tickerliste von Wikipedia.

Fallback-Kette (jede Stufe wird im Scan-Ergebnis sichtbar gemacht):
  1. Wikipedia (live) — bei Erfolg als "letzte gute Liste" gecacht
  2. cache/sp500_universe.json — letzte erfolgreich geladene Liste
  3. hartcodierte Top-100 (Notnagel; verzerrt das RS-Perzentil-Ranking!)

get_universe_info() liefert Quelle + Größe des letzten Abrufs — die UI
warnt damit, wenn der Scan auf einem degradierten Universum lief.
"""

import json
import os
import pandas as pd
import logging

logger = logging.getLogger(__name__)

SP500_WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_UNIVERSE_CACHE = os.path.join(os.path.dirname(__file__), "..", "cache", "sp500_universe.json")

# Metadaten des letzten Abrufs: {"source": "wikipedia"|"cache"|"fallback", "n": int}
_last_info: dict = {"source": None, "n": 0}


def get_sp500_tickers() -> list[str]:
    """Gibt eine Liste aller S&P500-Ticker zurück."""
    return [t for t, _ in _fetch_sp500_table()]


def get_sp500_names() -> dict[str, str]:
    """Gibt ein Dict {Ticker: Firmenname} für alle S&P500-Titel zurück."""
    return {t: n for t, n in _fetch_sp500_table()}


def get_universe_info() -> dict:
    """Quelle + Größe der zuletzt geladenen Tickerliste (für UI-Warnungen)."""
    return dict(_last_info)


def _fetch_sp500_table() -> list[tuple[str, str]]:
    """Lädt Ticker + Firmennamen von Wikipedia, mit zweistufigem Fallback."""
    global _last_info
    try:
        # User-Agent nötig — Wikipedia blockt Requests ohne ihn mit HTTP 403.
        # Ohne diesen Header fiele das Tool still auf die 100er-Fallback-Liste zurück.
        tables = pd.read_html(
            SP500_WIKI_URL,
            storage_options={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        df = tables[0]
        result = []
        for _, row in df.iterrows():
            ticker = str(row["Symbol"]).replace(".", "-")
            # pandas Series: direkte Indexierung robuster als .get()
            try:
                name = str(row["Security"])
            except KeyError:
                try:
                    name = str(row["Company"])
                except KeyError:
                    name = ticker
            if name in ("nan", "None", ""):
                name = ticker
            result.append((ticker, name))
        if len(result) < 400:
            # Layout-Änderung/Teilantwort: lieber Fallback als stilles Mini-Universum
            raise ValueError(f"Wikipedia lieferte nur {len(result)} Titel")
        logger.info(f"S&P500-Tabelle geladen: {len(result)} Titel")
        _save_universe_cache(result)
        _last_info = {"source": "wikipedia", "n": len(result)}
        return result
    except Exception as e:
        logger.warning(f"Wikipedia-Abruf fehlgeschlagen: {e} — versuche letzte gute Liste")

    cached = _load_universe_cache()
    if cached:
        logger.warning(f"Nutze gecachte Universum-Liste ({len(cached)} Titel)")
        _last_info = {"source": "cache", "n": len(cached)}
        return cached

    logger.warning("Kein Universum-Cache — nutze hartcodierte Top-100-Fallback-Liste")
    fb = _fallback_table()
    _last_info = {"source": "fallback", "n": len(fb)}
    return fb


def _save_universe_cache(table: list[tuple[str, str]]):
    try:
        os.makedirs(os.path.dirname(_UNIVERSE_CACHE), exist_ok=True)
        tmp = _UNIVERSE_CACHE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False)
        os.replace(tmp, _UNIVERSE_CACHE)
    except Exception as e:
        logger.debug(f"Universum-Cache Schreibfehler: {e}")


def _load_universe_cache() -> list[tuple[str, str]] | None:
    try:
        with open(_UNIVERSE_CACHE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) >= 400:
            return [(str(t), str(n)) for t, n in data]
    except Exception:
        pass
    return None


def _fallback_tickers() -> list[str]:
    """Kompatibilitäts-Wrapper — gibt nur Ticker zurück."""
    return [t for t, _ in _fallback_table()]


def _fallback_table() -> list[tuple[str, str]]:
    """Fallback: Top-100 S&P500-Titel mit Firmennamen."""
    return [
        ("AAPL",  "Apple Inc."),
        ("MSFT",  "Microsoft Corporation"),
        ("NVDA",  "NVIDIA Corporation"),
        ("AMZN",  "Amazon.com Inc."),
        ("GOOGL", "Alphabet Inc. (Class A)"),
        ("META",  "Meta Platforms Inc."),
        ("TSLA",  "Tesla Inc."),
        ("BRK-B", "Berkshire Hathaway Inc."),
        ("AVGO",  "Broadcom Inc."),
        ("JPM",   "JPMorgan Chase & Co."),
        ("LLY",   "Eli Lilly and Company"),
        ("V",     "Visa Inc."),
        ("UNH",   "UnitedHealth Group Inc."),
        ("XOM",   "Exxon Mobil Corporation"),
        ("MA",    "Mastercard Inc."),
        ("JNJ",   "Johnson & Johnson"),
        ("PG",    "Procter & Gamble Co."),
        ("HD",    "Home Depot Inc."),
        ("COST",  "Costco Wholesale Corporation"),
        ("MRK",   "Merck & Co. Inc."),
        ("ABBV",  "AbbVie Inc."),
        ("CVX",   "Chevron Corporation"),
        ("KO",    "Coca-Cola Company"),
        ("BAC",   "Bank of America Corporation"),
        ("CRM",   "Salesforce Inc."),
        ("NFLX",  "Netflix Inc."),
        ("AMD",   "Advanced Micro Devices Inc."),
        ("PEP",   "PepsiCo Inc."),
        ("TMO",   "Thermo Fisher Scientific Inc."),
        ("ORCL",  "Oracle Corporation"),
        ("ACN",   "Accenture plc"),
        ("ADBE",  "Adobe Inc."),
        ("WMT",   "Walmart Inc."),
        ("MCD",   "McDonald's Corporation"),
        ("ABT",   "Abbott Laboratories"),
        ("PM",    "Philip Morris International Inc."),
        ("DHR",   "Danaher Corporation"),
        ("CSCO",  "Cisco Systems Inc."),
        ("GE",    "GE Aerospace"),
        ("TXN",   "Texas Instruments Inc."),
        ("NEE",   "NextEra Energy Inc."),
        ("CAT",   "Caterpillar Inc."),
        ("VZ",    "Verizon Communications Inc."),
        ("AMGN",  "Amgen Inc."),
        ("IBM",   "International Business Machines Corp."),
        ("MS",    "Morgan Stanley"),
        ("RTX",   "RTX Corporation"),
        ("INTC",  "Intel Corporation"),
        ("HON",   "Honeywell International Inc."),
        ("INTU",  "Intuit Inc."),
        ("UPS",   "United Parcel Service Inc."),
        ("GS",    "Goldman Sachs Group Inc."),
        ("QCOM",  "QUALCOMM Inc."),
        ("SPGI",  "S&P Global Inc."),
        ("BKNG",  "Booking Holdings Inc."),
        ("LOW",   "Lowe's Companies Inc."),
        ("ELV",   "Elevance Health Inc."),
        ("T",     "AT&T Inc."),
        ("AXP",   "American Express Company"),
        ("AMAT",  "Applied Materials Inc."),
        ("ISRG",  "Intuitive Surgical Inc."),
        ("PLD",   "Prologis Inc."),
        ("DE",    "Deere & Company"),
        ("TJX",   "TJX Companies Inc."),
        ("MDT",   "Medtronic plc"),
        ("BLK",   "BlackRock Inc."),
        ("GILD",  "Gilead Sciences Inc."),
        ("SYK",   "Stryker Corporation"),
        ("VRTX",  "Vertex Pharmaceuticals Inc."),
        ("ADI",   "Analog Devices Inc."),
        ("REGN",  "Regeneron Pharmaceuticals Inc."),
        ("MMC",   "Marsh & McLennan Companies Inc."),
        ("CI",    "Cigna Group"),
        ("MO",    "Altria Group Inc."),
        ("ZTS",   "Zoetis Inc."),
        ("LRCX",  "Lam Research Corporation"),
        ("PGR",   "Progressive Corporation"),
        ("PANW",  "Palo Alto Networks Inc."),
        ("SO",    "Southern Company"),
        ("DUK",   "Duke Energy Corporation"),
        ("ICE",   "Intercontinental Exchange Inc."),
        ("BSX",   "Boston Scientific Corporation"),
        ("CME",   "CME Group Inc."),
        ("AON",   "Aon plc"),
        ("CL",    "Colgate-Palmolive Company"),
        ("HCA",   "HCA Healthcare Inc."),
        ("MCO",   "Moody's Corporation"),
        ("WM",    "Waste Management Inc."),
        ("NOC",   "Northrop Grumman Corporation"),
        ("ETN",   "Eaton Corporation plc"),
        ("EMR",   "Emerson Electric Co."),
        ("ITW",   "Illinois Tool Works Inc."),
        ("FI",    "Fiserv Inc."),
        ("APH",   "Amphenol Corporation"),
        ("GD",    "General Dynamics Corporation"),
        ("ROP",   "Roper Technologies Inc."),
        ("ADP",   "Automatic Data Processing Inc."),
        ("NSC",   "Norfolk Southern Corporation"),
        ("KLAC",  "KLA Corporation"),
    ]
