"""
Portfolio-Verwaltung: Käufe, Lots und realisierte Trades in data/portfolio.json.

Speicherformat (siehe portfolio/github_store.py):
    {
      "positions": [
        {"ticker", "company_name", "sector",
         "lots": [{"id", "date", "shares", "price_eur", "notes"}, ...]},
        ...
      ],
      "realized": [
        {"id", "ticker", "company_name", "buy_date", "sell_date", "shares",
         "buy_price_eur", "sell_price_eur", "pnl_eur", "pnl_pct", "days_held", "notes"},
        ...
      ]
    }

Lokal wird direkt in die Datei geschrieben; auf Streamlit Cloud committet
github_store die Datei per GitHub-API ins Repo (dort kann git zur Laufzeit nicht
schreiben). Ein-Nutzer-Setup: keine user_id-Trennung mehr.
"""

import uuid
from datetime import date, datetime
import yfinance as yf

from portfolio import github_store
from analyzer.exits import compute_exits, inject_external_signals


# ── Laden / Speichern ─────────────────────────────────────────────────────────

def _load() -> tuple[dict, str | None]:
    """Lädt (portfolio_dict, sha). sha nur im Cloud-Modus relevant."""
    return github_store.load()


def _save(data: dict, sha: str | None, message: str) -> None:
    github_store.save(data, sha, message)


def _new_id() -> str:
    return str(uuid.uuid4())


def _find_position(data: dict, ticker: str) -> dict | None:
    ticker = ticker.upper()
    for pos in data.get("positions", []):
        if pos.get("ticker", "").upper() == ticker:
            return pos
    return None


# ── Hilfsfunktionen für Lot-Kennzahlen ────────────────────────────────────────

def _total_shares_from_lots(lots: list[dict]) -> float:
    return sum(float(l["shares"]) for l in lots)


def _avg_price_from_lots(lots: list[dict]) -> float | None:
    total_s = sum(float(l["shares"]) for l in lots)
    if not total_s:
        return None
    return sum(float(l["shares"]) * float(l["price_eur"]) for l in lots) / total_s


def _earliest_date_from_lots(lots: list[dict]) -> date | None:
    dates = []
    for l in lots:
        try:
            dates.append(datetime.strptime(l["date"], "%Y-%m-%d").date())
        except Exception:
            pass
    return min(dates) if dates else None


# ── Käufe ─────────────────────────────────────────────────────────────────────

def add_position(ticker: str, company_name: str, entry_date: str,
                 entry_price_eur: float, shares: float, notes: str = "") -> dict:
    """Fügt ein neues Lot ein (neue oder bestehende Position). Gibt das Lot zurück."""
    ticker = ticker.upper().strip()
    data, sha = _load()

    pos = _find_position(data, ticker)
    if pos is None:
        # Sektor hier ermitteln statt beim Anzeigen: das ist ein echter
        # Mutationspunkt, der ohnehin speichert (evaluate_positions ist lesend).
        sector = None
        try:
            from analyzer.fundamentals_cache import get_info_cached
            sector = get_info_cached(ticker).get("sector")
        except Exception:
            pass
        pos = {
            "ticker": ticker,
            "company_name": company_name or ticker,
            "sector": sector,
            "lots": [],
        }
        data.setdefault("positions", []).append(pos)
    elif company_name:
        # Firmennamen aktuell halten
        pos["company_name"] = company_name

    lot = {
        "id": _new_id(),
        "date": str(entry_date),
        "shares": float(shares),
        "price_eur": float(entry_price_eur),
        "notes": notes,
    }
    pos["lots"].append(lot)

    _save(data, sha, f"Portfolio: Kauf {ticker} {shares:g}@{entry_price_eur:.2f}")
    return lot


def remove_position(ticker: str):
    """Entfernt alle Lots einer Position (ohne realized-Eintrag)."""
    ticker = ticker.upper()
    data, sha = _load()
    before = len(data.get("positions", []))
    data["positions"] = [
        p for p in data.get("positions", []) if p.get("ticker", "").upper() != ticker
    ]
    if len(data["positions"]) != before:
        _save(data, sha, f"Portfolio: Position {ticker} gelöscht")


# ── Bearbeitungen ─────────────────────────────────────────────────────────────

def edit_lot(lot_id: str, new_date: str, new_shares: float,
             new_price_eur: float, new_notes: str = "") -> str | None:
    """Ändert ein Lot per ID. Gibt None bei Erfolg, sonst eine Fehlermeldung."""
    try:
        datetime.strptime(new_date, "%Y-%m-%d")
    except Exception:
        return f"Ungültiges Datum: {new_date} (Format YYYY-MM-DD erwartet)."
    if new_shares <= 0:
        return "Stückzahl muss größer als 0 sein."
    if new_price_eur <= 0:
        return "Kaufkurs muss größer als 0 sein."

    data, sha = _load()
    for pos in data.get("positions", []):
        for lot in pos.get("lots", []):
            if lot.get("id") == lot_id:
                lot["date"] = new_date
                lot["shares"] = float(new_shares)
                lot["price_eur"] = float(new_price_eur)
                lot["notes"] = new_notes
                _save(data, sha, f"Portfolio: Lot {pos.get('ticker','')} bearbeitet")
                return None
    return "Lot nicht gefunden."


def delete_lot(lot_id: str, ticker: str) -> str | None:
    """Löscht ein Lot per ID. Letztes Lot einer Position kann nicht gelöscht werden."""
    data, sha = _load()
    pos = _find_position(data, ticker)
    if pos is None:
        return "Position nicht gefunden."
    lots = pos.get("lots", [])
    if len(lots) <= 1:
        return "Letztes Lot kann nicht gelöscht werden — nutze 'Position löschen'."
    new_lots = [l for l in lots if l.get("id") != lot_id]
    if len(new_lots) == len(lots):
        return "Lot nicht gefunden."
    pos["lots"] = new_lots
    _save(data, sha, f"Portfolio: Lot {ticker.upper()} gelöscht")
    return None


def edit_realized(trade_id: str, new_sell_date: str, new_shares: float,
                  new_sell_price_eur: float, new_notes: str = "") -> str | None:
    """Ändert einen realisierten Trade per ID und berechnet P&L neu."""
    try:
        sell_dt = datetime.strptime(new_sell_date, "%Y-%m-%d").date()
    except Exception:
        return f"Ungültiges Datum: {new_sell_date} (Format YYYY-MM-DD erwartet)."
    if sell_dt > date.today():
        return "Verkaufsdatum darf nicht in der Zukunft liegen."
    if new_shares <= 0:
        return "Stückzahl muss größer als 0 sein."
    if new_sell_price_eur <= 0:
        return "Verkaufskurs muss größer als 0 sein."

    data, sha = _load()
    for trade in data.get("realized", []):
        if trade.get("id") == trade_id:
            buy_price = float(trade.get("buy_price_eur", 0))
            pnl_eur = round((new_sell_price_eur - buy_price) * new_shares, 2)
            pnl_pct = round((new_sell_price_eur / buy_price - 1) * 100, 2) if buy_price else None
            try:
                buy_dt = datetime.strptime(trade["buy_date"], "%Y-%m-%d").date()
                days_held = (sell_dt - buy_dt).days
            except Exception:
                days_held = None

            trade["sell_date"] = new_sell_date
            trade["shares"] = float(new_shares)
            trade["sell_price_eur"] = float(new_sell_price_eur)
            trade["pnl_eur"] = pnl_eur
            trade["pnl_pct"] = pnl_pct
            trade["days_held"] = days_held
            trade["notes"] = new_notes
            _save(data, sha, f"Portfolio: Trade {trade.get('ticker','')} bearbeitet")
            return None
    return "Trade nicht gefunden."


# ── Verkäufe ──────────────────────────────────────────────────────────────────

def sell_position(ticker: str, shares: float, sell_price_eur: float,
                  sell_date: str, notes: str = "") -> tuple[list[dict], str | None]:
    """
    Verkauft (Teil-)Anteile nach FIFO-Prinzip.

    Returns:
        (realized_entries, error_message)
    """
    ticker = ticker.upper().strip()

    data, sha = _load()
    pos = _find_position(data, ticker)
    lots = pos.get("lots", []) if pos else []
    if not lots:
        return [], f"Position '{ticker}' nicht gefunden."

    total = _total_shares_from_lots(lots)

    if shares <= 0:
        return [], "Stückzahl muss größer als 0 sein."
    if shares > total + 0.0001:
        return [], f"Nur {total:g} Stück vorhanden, aber {shares:g} angegeben."
    if sell_price_eur <= 0:
        return [], "Verkaufskurs muss größer als 0 sein."

    try:
        sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
    except Exception:
        return [], f"Ungültiges Datum: {sell_date} (Format YYYY-MM-DD erwartet)."

    if sell_dt > date.today():
        return [], "Verkaufsdatum darf nicht in der Zukunft liegen."

    earliest = _earliest_date_from_lots(lots)
    if earliest and sell_dt < earliest:
        return [], (
            f"Verkaufsdatum {sell_date} liegt vor dem frühesten Kaufdatum "
            f"{earliest.isoformat()} dieser Position."
        )

    company_name = pos.get("company_name", ticker)

    # FIFO: Lots chronologisch abarbeiten
    sorted_lots = sorted(lots, key=lambda l: l["date"])
    remaining = float(shares)
    realized_entries = []
    lot_ids_to_delete = set()
    lot_new_shares: dict[str, float] = {}

    for lot in sorted_lots:
        if remaining <= 0.0001:
            break
        lot_shares = float(lot["shares"])
        sold = min(lot_shares, remaining)

        pnl_eur = round((float(sell_price_eur) - float(lot["price_eur"])) * sold, 2)
        pnl_pct = round((float(sell_price_eur) / float(lot["price_eur"]) - 1) * 100, 2) if lot["price_eur"] else None
        try:
            buy_dt = datetime.strptime(lot["date"], "%Y-%m-%d").date()
            days_held = (sell_dt - buy_dt).days
        except Exception:
            days_held = None

        realized_entries.append({
            "id": _new_id(),
            "ticker": ticker,
            "company_name": company_name,
            "buy_date": lot["date"],
            "sell_date": sell_date,
            "shares": round(sold, 6),
            "buy_price_eur": float(lot["price_eur"]),
            "sell_price_eur": float(sell_price_eur),
            "pnl_eur": pnl_eur,
            "pnl_pct": pnl_pct,
            "days_held": days_held,
            "notes": notes,
        })

        new_shares = round(lot_shares - sold, 6)
        if new_shares < 0.0001:
            lot_ids_to_delete.add(lot["id"])
        else:
            lot_new_shares[lot["id"]] = new_shares

        remaining -= sold

    # Lots aktualisieren/entfernen
    updated_lots = []
    for lot in lots:
        if lot["id"] in lot_ids_to_delete:
            continue
        if lot["id"] in lot_new_shares:
            lot["shares"] = lot_new_shares[lot["id"]]
        updated_lots.append(lot)
    pos["lots"] = updated_lots

    # Position ohne Lots komplett entfernen
    if not updated_lots:
        data["positions"] = [
            p for p in data.get("positions", []) if p.get("ticker", "").upper() != ticker
        ]

    data.setdefault("realized", []).extend(realized_entries)

    _save(data, sha, f"Portfolio: Verkauf {ticker} {shares:g}@{sell_price_eur:.2f}")
    return realized_entries, None


def load_realized() -> list[dict]:
    """Gibt alle realisierten Trades zurück (neueste zuerst)."""
    data, _ = _load()
    realized = list(data.get("realized", []))
    realized.sort(key=lambda r: r.get("sell_date", ""), reverse=True)
    return realized


# ── Live-Daten ────────────────────────────────────────────────────────────────

def _batch_history(tickers: list[str], period: str = "3mo") -> dict:
    """
    Ein yf.download-Call für alle Portfolio-Ticker statt N Einzelcalls
    (schneller, weniger Rate-Limit-Risiko). Ticker ohne Daten fehlen im Dict.
    """
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period=period, auto_adjust=True,
                          progress=False, group_by="ticker", threads=False)
        if raw is None or raw.empty:
            return {}
        out = {}
        for t in tickers:
            try:
                df = raw[t].copy() if len(tickers) > 1 else raw.copy()
                df = df.dropna(how="all")
                if len(df) >= 15:
                    out[t] = df
            except Exception:
                pass
        return out
    except Exception:
        return {}


def get_eurusd_rate() -> float | None:
    """Aktueller EUR/USD-Kurs. None bei Fehler."""
    try:
        hist = yf.Ticker("EURUSD=X").history(period="5d")
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def evaluate_positions(market_bearish: bool | None = None) -> list[dict]:
    """
    Lädt alle offenen Lots, gruppiert nach Ticker, berechnet P&L und Exit-Signale.

    NUR LESEND — diese Funktion darf das Portfolio nicht schreiben. Auf Streamlit
    Cloud geht jeder Schreibvorgang als echter Commit über die GitHub-API; früher
    löste hier das Nachtragen gefundener Sektoren einen Commit aus, nur weil
    jemand die Seite ansah (und zwei offene Tabs einen ConflictError).

    market_bearish: vorberechnetes Marktumfeld (views/common.cached_market()).
                    None → wird selbst ermittelt (für Skripte/Notebooks).
    """
    data, _sha = _load()
    eurusd = get_eurusd_rate()

    if market_bearish is None:
        try:
            from analyzer.market_filter import check_market
            mkt = check_market()
            market_bearish = not mkt.get("passed", True) or mkt.get("warning", False)
        except Exception:
            market_bearish = False

    positions = data.get("positions", [])
    hist_batch = _batch_history([p["ticker"] for p in positions if p.get("lots")])

    results = []
    for pos in positions:
        ticker = pos["ticker"]
        ticker_lots = pos.get("lots", [])
        if not ticker_lots:
            continue

        total_shares = _total_shares_from_lots(ticker_lots)
        avg_entry_eur = _avg_price_from_lots(ticker_lots)
        earliest_dt = _earliest_date_from_lots(ticker_lots)
        days_held = (date.today() - earliest_dt).days if earliest_dt else None
        company_name = pos.get("company_name", ticker)
        sector = pos.get("sector")

        current_price_usd = None
        current_price_eur = None
        exits = {"atr": None, "stop_loss": None, "take_profit": None,
                 "signals": {}, "signal_count": 0, "recommendation": "Keine Daten"}

        try:
            hist = hist_batch.get(ticker)
            if hist is None or len(hist) < 15:
                hist = yf.Ticker(ticker).history(period="3mo")
            if hist is not None and len(hist) >= 15:
                current_price_usd = float(hist["Close"].iloc[-1])
                if eurusd:
                    current_price_eur = round(current_price_usd / eurusd, 2)
                avg_entry_usd = (avg_entry_eur * eurusd) if (avg_entry_eur and eurusd) else None
                exits = compute_exits(hist, entry_price=current_price_usd,
                                      avg_entry_price=avg_entry_usd)
                if exits["signals"]:
                    inject_external_signals(exits, **{"Marktumfeld bearish": market_bearish})
                # Kurswerte für die Anzeige in EUR umrechnen
                if eurusd and eurusd > 0:
                    for key in ("stop_loss", "take_profit"):
                        if exits.get(key) is not None:
                            exits[key] = round(exits[key] / eurusd, 2)
            if not sector:
                # Nur für die Anzeige — NICHT nach pos["sector"] zurückschreiben
                # (siehe Docstring). Persistiert wird der Sektor in add_position().
                # get_info_cached statt yf.Ticker().info: 3-Tage-TTL statt eines
                # 1-2 s teuren Calls pro Position bei jedem Seitenaufruf.
                try:
                    from analyzer.fundamentals_cache import get_info_cached
                    sector = get_info_cached(ticker).get("sector")
                except Exception:
                    pass
        except Exception:
            pass

        pnl_abs_eur = None
        pnl_pct = None
        # avg_entry_eur == 0 möglich (z.B. fehlender Kaufkurs) → kein P&L statt Crash
        if avg_entry_eur and current_price_eur is not None:
            pnl_abs_eur = round((current_price_eur - avg_entry_eur) * total_shares, 2)
            pnl_pct = round((current_price_eur / avg_entry_eur - 1) * 100, 2)

        # Lots ins erwartete Anzeigeformat bringen (date/price_eur)
        lots_compat = [
            {
                "id": l["id"],
                "date": l["date"],
                "shares": l["shares"],
                "price_eur": l["price_eur"],
                "notes": l.get("notes", ""),
            }
            for l in sorted(ticker_lots, key=lambda x: x["date"])
        ]

        results.append({
            "ticker": ticker,
            "company_name": company_name,
            "lots": lots_compat,
            "total_shares": total_shares,
            "avg_entry_price_eur": round(avg_entry_eur, 2) if avg_entry_eur else None,
            "entry_date": earliest_dt.isoformat() if earliest_dt else None,
            "sector": sector,
            "current_price_usd": current_price_usd,
            "current_price_eur": current_price_eur,
            "eurusd": eurusd,
            "days_held": days_held,
            "pnl_abs_eur": pnl_abs_eur,
            "pnl_pct": pnl_pct,
            "exits": exits,
            "notes": lots_compat[-1].get("notes", "") if lots_compat else "",
        })

    return results
