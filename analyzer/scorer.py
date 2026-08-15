"""
Haupt-Analyse-Engine:
Lädt alle S&P500-Aktien, führt alle 4 Gates durch und gibt
eine Liste der empfohlenen Aktien zurück.
"""

import yfinance as yf
import pandas as pd
import numpy as np
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from analyzer.universe import get_sp500_tickers, get_universe_info
from analyzer.market_filter import check_market
from analyzer.relative_strength import check_relative_strength
from analyzer.technical import check_technical
from analyzer.fundamental import check_fundamental
from analyzer.fundamentals_cache import get_info_cached
from analyzer.confidence import compute_confidence
from analyzer.exits import compute_exits, inject_external_signals
from analyzer.upside import compute_upside
from config import ANALYSIS, RELATIVE_STRENGTH, TECHNICAL, RECOMMENDER_V2
from analyzer.price_cache import load_many as _cache_load_many, save_many as _cache_save_many

logger = logging.getLogger(__name__)


_SLIM_KEYS = ("ticker", "name", "sector", "recommended",
              "gate_rs", "gate_tech", "gate_fund",
              "tech_score", "fund_score", "combined_score",
              "confidence_label", "price",
              # v2-Parallelalgorithmus (additiv)
              "recommended_v2", "gate_rs_v2", "trend_ok", "not_overbought",
              # v2-Rang (1..top_n) + MACD als Tiebreaker-Anzeige
              "v2_rank", "macd_bull")


def _slim(r: dict) -> dict:
    s = {k: r.get(k) for k in _SLIM_KEYS}
    rs = r.get("rs", {})
    s["rs"] = {
        "rs_3m": rs.get("rs_3m"),
        "rs_6m": rs.get("rs_6m"),
        "rs_score": rs.get("rs_score"),
    }
    return s


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
        # Gleiches Schema wie der Erfolgspfad. Fehlten hier recommendations_v2 und
        # universe, würde die UI still danebengreifen (Universum-Banner ausgelassen,
        # v2-Panel meldet fälschlich "älterer Cache").
        # universe bewusst hartcodiert statt get_universe_info(): auf diesem Pfad
        # wurde nie eine Tickerliste geholt — source=None heißt korrekt "kein Scan".
        return {
            "timestamp": timestamp,
            "market": market,
            "recommendations": [],
            "recommendations_v2": [],
            "all_results": [],
            "scan_duration_s": round(time.time() - start, 1),
            "universe": {"source": None, "n": 0},
            "scan_stats": {"requested": 0, "analyzed": 0, "rs_ranked": 0,
                           "skipped_market_gate": True},
        }

    # S&P500-Tickerliste
    tickers = get_sp500_tickers()
    total = len(tickers)
    logger.info(f"Starte Scan für {total} Titel...")

    # S&P500-Kursdaten für relative Stärke — aus check_market() wiederverwenden
    sp500_hist = market.get("sp500_hist")
    if sp500_hist is None or len(sp500_hist) < 60:
        sp500_hist = _get_sp500_history()

    # Batch-Download aller Kursdaten — drastisch weniger HTTP-Requests als Einzelcalls
    hist_cache = _batch_download(tickers)
    logger.info(f"Batch-Download: {len(hist_cache)}/{total} Ticker geladen")

    # Analyse: nur Kursdaten-Verarbeitung parallelisieren (kein Netzwerk)
    results = []
    missing_tickers = []
    with ThreadPoolExecutor(max_workers=ANALYSIS["max_workers"]) as executor:
        futures = {
            executor.submit(_analyze_ticker, ticker, sp500_hist, hist_cache.get(ticker), market): ticker
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
                else:
                    missing_tickers.append(ticker)
            except Exception as e:
                logger.warning(f"{ticker}: {e}")
                missing_tickers.append(ticker)
            if progress_callback:
                progress_callback(done, total, ticker)

    # Retry für Ticker ohne Batch-Daten — Einzelcalls mit Delay
    if missing_tickers:
        logger.info(f"Einzelcall-Retry für {len(missing_tickers)} Ticker ohne Batch-Daten...")
        time.sleep(3)
        with ThreadPoolExecutor(max_workers=2) as executor:
            retry_futures = {
                executor.submit(_analyze_ticker, ticker, sp500_hist, None, market): ticker
                for ticker in missing_tickers
            }
            for future in as_completed(retry_futures):
                ticker = retry_futures[future]
                try:
                    res = future.result()
                    if res:
                        results.append(res)
                except Exception as e:
                    logger.warning(f"Retry {ticker}: {e}")

    # Fundamentals-Cache einmal auf Platte schreiben (statt bei jedem Ticker)
    try:
        from analyzer.fundamentals_cache import flush as _flush_fundamentals
        _flush_fundamentals()
    except Exception as e:
        logger.debug(f"Fundamentals-Cache-Flush: {e}")

    # Gate-2-Post-Pass: RS-Perzentil-Ranking über alle analysierten Ticker
    results = _apply_rs_percentile(results, market)

    # Sortierung: Empfehlungen zuerst, dann nach Tech-Score
    results.sort(key=lambda x: (not x["recommended"], -x["tech_score"]))
    recommendations = [r for r in results if r["recommended"]]
    # v2-Parallelliste: nach RS-Score sortiert (v2s primäres Signal), geslimmt
    # (kein hist/Charts nötig — dient dem Vergleich, nicht der Detailansicht).
    recommendations_v2 = [
        _slim(r) for r in sorted(
            (r for r in results if r.get("recommended_v2")),
            key=lambda x: -(x.get("rs", {}).get("rs_score") or 0),
        )
    ]
    all_results = [_slim(r) for r in results]

    logger.info(f"Scan abgeschlossen: {len(recommendations)} v1-Empfehlungen, "
                f"{len(recommendations_v2)} v2-Empfehlungen aus {len(results)} Titeln")

    rs_ranked = sum(1 for r in results if (r.get("rs") or {}).get("rs_score") is not None)

    return {
        "timestamp": timestamp,
        "market": market,
        "recommendations": recommendations,
        "recommendations_v2": recommendations_v2,
        "all_results": all_results,
        "scan_duration_s": round(time.time() - start, 1),
        # Quelle/Größe der Tickerliste — UI warnt bei degradiertem Universum
        # (Fallback verschiebt das RS-Perzentil-Ranking komplett).
        "universe": get_universe_info(),
        # Wie viel vom Universum tatsächlich durchkam. Ticker, die an einer
        # Exception scheitern, fallen nach einem Retry still weg — und der
        # RS-Perzentil-Cutoff wird relativ zu genau dieser Restmenge berechnet.
        # Ein Scan über 300 statt 503 Titel verschiebt also jede Gate-2-Schwelle;
        # ohne diese Zahlen wäre das nirgends sichtbar.
        "scan_stats": {
            "requested": total,
            "analyzed": len(results),
            "rs_ranked": rs_ranked,   # Basis des Perzentil-Cutoffs
            "skipped_market_gate": False,
        },
    }


def _apply_rs_percentile(results: list, market: dict) -> list:
    """
    Überschreibt gate_rs und recommended mit perzentil-basiertem RS-Ranking.

    Statt eines harten >0-Schnitts qualifizieren nur Aktien im Top-X%-Perzentil
    nach rs_score (= rs_3m + rs_6m) UND mit rs_6m >= rs_min_6m (absoluter Floor).
    """
    top_pct = RELATIVE_STRENGTH.get("rs_top_percentile", 0.33)
    min_6m = RELATIVE_STRENGTH.get("rs_min_6m", 0.0)
    top_pct_v2 = RECOMMENDER_V2.get("rs_top_percentile", 0.20)

    # Nur Ergebnisse mit gültigem rs_score
    valid = [r for r in results if r.get("rs", {}).get("rs_score") is not None]
    if not valid:
        return results

    scores = [r["rs"]["rs_score"] for r in valid]
    cutoff = float(np.percentile(scores, (1 - top_pct) * 100))
    cutoff_v2 = float(np.percentile(scores, (1 - top_pct_v2) * 100))
    logger.info(f"RS-Perzentil-Cutoff v1 (top {int(top_pct*100)}%): {cutoff:.2f} | "
                f"v2 (top {int(top_pct_v2*100)}%): {cutoff_v2:.2f} | "
                f"Basis: {len(valid)} Titel mit gültigem RS-Score")

    for r in results:
        rs = r.get("rs", {})
        rs_score = rs.get("rs_score")
        rs_6m = rs.get("rs_6m") or 0.0

        if rs_score is None:
            gate_rs = False
            gate_rs_v2 = False
        else:
            gate_rs = bool(rs_score >= cutoff and rs_6m >= min_6m)
            gate_rs_v2 = bool(rs_score >= cutoff_v2 and rs_6m >= min_6m)

        r["gate_rs"] = gate_rs
        r["rs"]["passed"] = gate_rs
        r["recommended"] = gate_rs and r.get("gate_tech", False) and r.get("gate_fund", False)

        # v2-Parallelalgorithmus: strengerer RS-Schnitt + Trend-Pflicht + nicht überkauft,
        # Gate 4 (Fundamentals) bleibt. Tech-Score-Schwelle (gate_tech) bewusst NICHT —
        # sie hatte im 10J-Backtest keine Vorhersagekraft.
        r["gate_rs_v2"] = gate_rs_v2
        r["recommended_v2"] = bool(
            gate_rs_v2 and r.get("trend_ok", False)
            and r.get("not_overbought", False) and r.get("gate_fund", False)
        )
        r["v2_rank"] = None

    # Top-N-Begrenzung: nur die N RS-stärksten v2-Survivors empfehlen.
    # Filter-Experimente (scripts/experiment_filters.py, 10J-Daten): Konzentration
    # auf Top-10 hebt vs SPY von +0,65 % auf +2,12 %/Monat bei 11/11 positiven
    # Jahren; die Top-5 sind nochmal stärker und werden via v2_rank markiert.
    top_n = RECOMMENDER_V2.get("top_n", 10)
    v2_survivors = sorted(
        (r for r in results if r["recommended_v2"]),
        key=lambda x: -(x.get("rs", {}).get("rs_score") or 0),
    )
    for rank, r in enumerate(v2_survivors, 1):
        if rank <= top_n:
            r["v2_rank"] = rank
        else:
            r["recommended_v2"] = False

    return results


def _batch_download(tickers: list) -> dict:
    """
    Lädt Kursdaten für alle Ticker in möglichst wenigen HTTP-Requests via yf.download().
    Gibt ein Dict {ticker: DataFrame} zurück. Ticker ohne ausreichende Daten fehlen.
    """
    # Zuerst Tages-Cache prüfen
    hist_cache, to_download = _cache_load_many(tickers)
    if hist_cache:
        logger.info(f"Preis-Cache: {len(hist_cache)} Treffer, {len(to_download)} müssen geladen werden")

    if not to_download:
        return hist_cache

    # yf.download akzeptiert maximal ~500 Ticker pro Call — wir machen ggf. 2 Batches
    batch_size = 250
    batches = [to_download[i:i + batch_size] for i in range(0, len(to_download), batch_size)]
    new_downloads = {}

    for batch_num, batch in enumerate(batches, 1):
        logger.info(f"Batch {batch_num}/{len(batches)}: {len(batch)} Ticker...")
        try:
            from config import NETWORK
            raw = yf.download(
                batch,
                period="1y",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                # Begrenztes Threading: threads=False lud ~500 Ticker sequenziell
                # (Minuten beim ersten Tages-Scan). 8 parallele Requests sind
                # weit unter Yahoos Rate-Limit, aber ~8x schneller.
                threads=8,
                # Explizites Request-Timeout — ein hängender Ticker darf den
                # ganzen Batch (und damit den Scan-Thread) nicht blockieren.
                timeout=NETWORK["request_timeout_sec"],
            )
            if raw is None or raw.empty:
                logger.warning(f"Batch {batch_num}: leere Antwort")
                continue

            for ticker in batch:
                try:
                    if len(batch) == 1:
                        df = raw.copy()
                    else:
                        df = raw[ticker].copy()
                    df = df.dropna(how="all")
                    if len(df) >= 60:
                        new_downloads[ticker] = df
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Batch {batch_num} fehlgeschlagen: {e}")

        if batch_num < len(batches):
            time.sleep(2)  # kurze Pause zwischen Batches

    # Neue Downloads cachen
    _cache_save_many(new_downloads)
    hist_cache.update(new_downloads)
    return hist_cache


def _get_sp500_history() -> pd.Series:
    try:
        sp = yf.Ticker("^GSPC")
        hist = sp.history(period="1y")
        return hist["Close"]
    except Exception as e:
        logger.error(f"S&P500-History-Fehler: {e}")
        return pd.Series(dtype=float)


def _analyze_ticker(ticker: str, sp500_hist: pd.Series,
                    prefetched_hist: pd.DataFrame | None = None,
                    market: dict | None = None) -> dict | None:
    try:
        if prefetched_hist is not None and len(prefetched_hist) >= 60:
            hist = prefetched_hist
            stock = None  # wird nur für .info (Gate 4) benötigt
        else:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1y")
            if hist is None or len(hist) < 60:
                return None

        close = hist["Close"]

        # Gate 2: Relative Stärke
        rs = check_relative_strength(close, sp500_hist)

        # Gate 3: Technische Analyse
        tech = check_technical(hist)

        # Gate 4: Fundamentalanalyse — nur wenn Gate 3 bestanden.
        # Gate 2 (RS-Rang) wird erst im Post-Pass bestimmt; Gate 3 als Filter reicht.
        # info kommt aus dem Fundamentals-Cache (TTL 3 Tage) — Ticker.info ist der
        # teuerste Einzelcall im Scan und ändert sich nur quartalsweise.
        if tech["passed"]:
            info = get_info_cached(ticker)
        else:
            info = {}
        fund = check_fundamental(info)

        recommended = rs["passed"] and tech["passed"] and fund["passed"]

        # v2-Parallelalgorithmus: strukturelle Filter (statt Tech-Score-Schwelle).
        # Trend = über MA50 UND MA200; nicht überkauft = unter oberem BB-Band UND RSI ≤ Max.
        _sig = tech.get("signals", {})
        _rsi_v = tech.get("indicators", {}).get("rsi_value")
        trend_ok = bool(_sig.get("Kurs über 50-Tage-MA") and _sig.get("Kurs über 200-Tage-MA"))
        not_overbought = bool(
            _sig.get("Nicht überkauft (Bollinger)")
            and _rsi_v is not None and _rsi_v <= TECHNICAL["rsi_max"]
        )

        # Additiv: Konfidenz-Ranking (ändert recommended nicht)
        _mkt = market or {}
        vix = _mkt.get("vix")
        confidence = compute_confidence(tech["score"], fund["score"], rs, vix=vix)

        # Additiv: Exit-Signale (externe Signale nachträglich setzen)
        current_price = tech["indicators"].get("price") if tech["indicators"] else None
        exits = compute_exits(hist, entry_price=current_price, vix=vix)
        if exits["signals"]:
            rs_6m = rs.get("rs_6m", 0) or 0
            # "Marktumfeld bearish" NUR bei echtem Gate-1-Versagen — nicht bei warning.
            # Eine Empfehlung existiert nur, weil Gate 1 den Markt akzeptiert hat; das
            # Warning-Regime steckt bereits im Konfidenz-Score (Regime-Gewichtung) und in
            # der strengeren Trailing-Drawdown-Schwelle. Es als zusätzliches per-Titel-
            # Verkaufssignal zu zählen, würde frische Kaufempfehlungen widersprüchlich auf
            # "Verkaufen erwägen" setzen. Für Bestandspositionen bleibt warning aktiv
            # (portfolio/manager.py).
            market_bearish = not _mkt.get("passed", True)
            _elevated = vix is not None and vix > 20
            # Das absolute 6M-Signal aus compute_exits durch das relative (vs. S&P500)
            # ersetzen — konsistent zur Einstiegslogik (Gate 2 verlangt rs_6m ≥ 0).
            # Entfernen verhindert Doppelzählung beider 6M-Varianten.
            exits["signals"].pop("6M-Rendite negativ (absolut)", None)
            inject_external_signals(
                exits,
                sell_threshold=2 if _elevated else None,
                **{"6M-Rendite negativ (vs. S&P500)": rs_6m < 0, "Marktumfeld bearish": market_bearish},
            )

        # Additiv: Erwartetes Upside
        upside = compute_upside(
            hist=hist,
            current_price=current_price,
            ma50=tech["indicators"].get("ma50_val") if tech["indicators"] else None,
            atr=exits.get("atr"),
            metrics=fund.get("metrics", {}),
        )

        return {
            "ticker": ticker,
            "name": fund["metrics"].get("name", ticker),
            "sector": fund["metrics"].get("sector", "N/A"),
            "recommended": recommended,
            # Gate-Ergebnisse
            "gate_rs": rs["passed"],
            "gate_tech": tech["passed"],
            "gate_fund": fund["passed"],
            # v2-Sub-Flags (RS-Schnitt folgt im Post-Pass)
            "trend_ok": trend_ok,
            "not_overbought": not_overbought,
            # MACD als Tiebreaker-Anzeige (kein Filter — kostet im Backtest Rendite,
            # verbessert aber den schlechtesten Trade deutlich; siehe FINDINGS.md)
            "macd_bull": bool(_sig.get("MACD bullisch")),
            # Scores
            "tech_score": tech["score"],
            "fund_score": fund["score"],
            # Konfidenz (additiv)
            "combined_score": confidence["combined_score"],
            "confidence_label": confidence["confidence_label"],
            "regime": confidence.get("regime", "normal"),
            # Exit-Signale (additiv)
            "exits": exits,
            # Upside (additiv)
            "upside": upside,
            # Detail-Daten (für Report)
            "rs": rs,
            "tech": tech,
            "fund": fund,
            "price": current_price,
            "hist": hist,
        }

    except Exception as e:
        logger.debug(f"{ticker} übersprungen: {e}")
        return None
