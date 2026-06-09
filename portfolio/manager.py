"""
Portfolio-Verwaltung: Käufe, Lots und realisierte Trades in Supabase speichern.

Tabellen (müssen in Supabase angelegt sein):
  lots             — offene Kaufpositionen (eine Zeile = ein Lot)
  realized_trades  — abgeschlossene Trades

Beide Tabellen haben Row-Level-Security: jeder Nutzer sieht nur seine eigenen Zeilen.
"""

import os
from datetime import date, datetime
import yfinance as yf

from portfolio.supabase_client import get_supabase
from portfolio.auth import current_user_id
from analyzer.exits import compute_exits, inject_external_signals

_LEGACY_JSON = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")


# ── Einmal-Migration aus portfolio.json ───────────────────────────────────────

def auto_migrate_from_json() -> str | None:
    """
    Prüft ob portfolio.json noch auf dem Server liegt und der Nutzer noch keine
    Supabase-Daten hat. Falls beides zutrifft, importiert sie die Daten automatisch.
    Gibt eine Status-Meldung zurück (oder None wenn nichts zu tun war).
    """
    import json as _json

    if not os.path.exists(_LEGACY_JSON):
        return None

    uid = _uid()
    sb = get_supabase()

    # Nur migrieren wenn noch keine Lots vorhanden
    existing = sb.table("lots").select("id").eq("user_id", uid).limit(1).execute()
    if existing.data:
        return None

    try:
        with open(_LEGACY_JSON, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except Exception:
        return None

    positions = data.get("positions", [])
    realized = data.get("realized", [])
    if not positions and not realized:
        return None

    lot_rows = []
    for pos in positions:
        ticker = pos.get("ticker", "").upper()
        company_name = pos.get("company_name", ticker)
        sector = pos.get("sector")
        lots = pos.get("lots") or [{
            "date": pos.get("entry_date", ""),
            "shares": pos.get("shares", 0),
            "price_eur": pos.get("entry_price_eur") or pos.get("entry_price") or 0,
            "notes": pos.get("notes", ""),
        }]
        for lot in lots:
            lot_rows.append({
                "user_id": uid, "ticker": ticker, "company_name": company_name,
                "sector": sector, "buy_date": lot.get("date", ""),
                "shares": float(lot.get("shares", 0)),
                "price_eur": float(lot.get("price_eur", 0)),
                "notes": lot.get("notes", ""),
            })

    trade_rows = []
    for trade in realized:
        trade_rows.append({
            "user_id": uid,
            "ticker": trade.get("ticker", "").upper(),
            "company_name": trade.get("company_name", ""),
            "buy_date": trade.get("buy_date", ""),
            "sell_date": trade.get("sell_date", ""),
            "shares": float(trade.get("shares", 0)),
            "buy_price_eur": float(trade.get("buy_price_eur", 0)),
            "sell_price_eur": float(trade.get("sell_price_eur", 0)),
            "pnl_eur": trade.get("pnl_eur"),
            "pnl_pct": trade.get("pnl_pct"),
            "days_held": trade.get("days_held"),
            "notes": trade.get("notes", ""),
        })

    if lot_rows:
        sb.table("lots").insert(lot_rows).execute()
    if trade_rows:
        sb.table("realized_trades").insert(trade_rows).execute()

    return (
        f"Daten aus portfolio.json automatisch migriert: "
        f"{len(lot_rows)} Lots, {len(trade_rows)} realisierte Trades."
    )


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _uid() -> str:
    uid = current_user_id()
    if not uid:
        raise RuntimeError("Kein Nutzer eingeloggt.")
    return uid


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
            dates.append(datetime.strptime(l["buy_date"], "%Y-%m-%d").date())
        except Exception:
            pass
    return min(dates) if dates else None


# ── Lots lesen ────────────────────────────────────────────────────────────────

def _fetch_lots(ticker: str | None = None) -> list[dict]:
    """Lädt alle Lots des eingeloggten Nutzers (optional nach Ticker gefiltert)."""
    sb = get_supabase()
    uid = _uid()
    q = sb.table("lots").select("*").eq("user_id", uid)
    if ticker:
        q = q.eq("ticker", ticker.upper())
    res = q.order("buy_date").execute()
    return res.data or []


def _fetch_realized() -> list[dict]:
    """Lädt alle realisierten Trades, neueste zuerst."""
    sb = get_supabase()
    uid = _uid()
    res = (
        sb.table("realized_trades")
        .select("*")
        .eq("user_id", uid)
        .order("sell_date", desc=True)
        .execute()
    )
    return res.data or []


# ── Käufe ─────────────────────────────────────────────────────────────────────

def add_position(ticker: str, company_name: str, entry_date: str,
                 entry_price_eur: float, shares: float, notes: str = "") -> dict:
    """
    Fügt ein neues Lot ein. Gibt den eingefügten Datensatz zurück.
    """
    ticker = ticker.upper().strip()
    sb = get_supabase()
    uid = _uid()

    # Firmennamen aktuell halten: falls Ticker bereits existiert, company_name übernehmen
    existing = sb.table("lots").select("company_name").eq("user_id", uid).eq("ticker", ticker).limit(1).execute()
    if existing.data and not company_name:
        company_name = existing.data[0].get("company_name", ticker)

    lot = {
        "user_id": uid,
        "ticker": ticker,
        "company_name": company_name or ticker,
        "buy_date": str(entry_date),
        "shares": float(shares),
        "price_eur": float(entry_price_eur),
        "notes": notes,
    }
    res = sb.table("lots").insert(lot).execute()
    return res.data[0] if res.data else lot


def remove_position(ticker: str):
    """Entfernt alle Lots einer Position (ohne realized-Eintrag)."""
    sb = get_supabase()
    sb.table("lots").delete().eq("user_id", _uid()).eq("ticker", ticker.upper()).execute()


# ── Bearbeitungen ─────────────────────────────────────────────────────────────

def edit_lot(lot_id: str, new_date: str, new_shares: float,
             new_price_eur: float, new_notes: str = "") -> str | None:
    """
    Ändert ein Lot per UUID.
    Gibt None bei Erfolg, sonst eine Fehlermeldung zurück.
    """
    try:
        datetime.strptime(new_date, "%Y-%m-%d")
    except Exception:
        return f"Ungültiges Datum: {new_date} (Format YYYY-MM-DD erwartet)."
    if new_shares <= 0:
        return "Stückzahl muss größer als 0 sein."
    if new_price_eur <= 0:
        return "Kaufkurs muss größer als 0 sein."

    sb = get_supabase()
    sb.table("lots").update({
        "buy_date": new_date,
        "shares": float(new_shares),
        "price_eur": float(new_price_eur),
        "notes": new_notes,
    }).eq("id", lot_id).eq("user_id", _uid()).execute()
    return None


def delete_lot(lot_id: str, ticker: str) -> str | None:
    """
    Löscht ein Lot per UUID.
    Letztes Lot einer Position kann nicht gelöscht werden.
    """
    sb = get_supabase()
    uid = _uid()
    remaining = sb.table("lots").select("id").eq("user_id", uid).eq("ticker", ticker.upper()).execute()
    if len(remaining.data or []) <= 1:
        return "Letztes Lot kann nicht gelöscht werden — nutze 'Position löschen'."
    sb.table("lots").delete().eq("id", lot_id).eq("user_id", uid).execute()
    return None


def edit_realized(trade_id: str, new_sell_date: str, new_shares: float,
                  new_sell_price_eur: float, new_notes: str = "") -> str | None:
    """
    Ändert einen realisierten Trade per UUID und berechnet P&L neu.
    """
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

    sb = get_supabase()
    uid = _uid()
    res = sb.table("realized_trades").select("buy_date,buy_price_eur").eq("id", trade_id).eq("user_id", uid).execute()
    if not res.data:
        return "Trade nicht gefunden."

    trade = res.data[0]
    buy_price = float(trade.get("buy_price_eur", 0))
    pnl_eur = round((new_sell_price_eur - buy_price) * new_shares, 2)
    pnl_pct = round((new_sell_price_eur / buy_price - 1) * 100, 2) if buy_price else None
    try:
        buy_dt = datetime.strptime(trade["buy_date"], "%Y-%m-%d").date()
        days_held = (sell_dt - buy_dt).days
    except Exception:
        days_held = None

    sb.table("realized_trades").update({
        "sell_date": new_sell_date,
        "shares": float(new_shares),
        "sell_price_eur": float(new_sell_price_eur),
        "pnl_eur": pnl_eur,
        "pnl_pct": pnl_pct,
        "days_held": days_held,
        "notes": new_notes,
    }).eq("id", trade_id).eq("user_id", uid).execute()
    return None


# ── Verkäufe ──────────────────────────────────────────────────────────────────

def sell_position(ticker: str, shares: float, sell_price_eur: float,
                  sell_date: str, notes: str = "") -> tuple[list[dict], str | None]:
    """
    Verkauft (Teil-)Anteile nach FIFO-Prinzip.

    Returns:
        (realized_entries, error_message)
    """
    ticker = ticker.upper().strip()

    lots = _fetch_lots(ticker)
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

    sb = get_supabase()
    uid = _uid()
    company_name = lots[0].get("company_name", ticker)

    # FIFO: Lots chronologisch abarbeiten
    sorted_lots = sorted(lots, key=lambda l: l["buy_date"])
    remaining = float(shares)
    realized_entries = []
    lots_to_delete = []
    lots_to_update = []

    for lot in sorted_lots:
        if remaining <= 0.0001:
            break
        lot_shares = float(lot["shares"])
        sold = min(lot_shares, remaining)

        pnl_eur = round((float(sell_price_eur) - float(lot["price_eur"])) * sold, 2)
        pnl_pct = round((float(sell_price_eur) / float(lot["price_eur"]) - 1) * 100, 2) if lot["price_eur"] else None
        try:
            buy_dt = datetime.strptime(lot["buy_date"], "%Y-%m-%d").date()
            days_held = (sell_dt - buy_dt).days
        except Exception:
            days_held = None

        realized_entries.append({
            "user_id": uid,
            "ticker": ticker,
            "company_name": company_name,
            "buy_date": lot["buy_date"],
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
            lots_to_delete.append(lot["id"])
        else:
            lots_to_update.append({"id": lot["id"], "shares": new_shares})

        remaining -= sold

    # DB-Updates
    for lot_id in lots_to_delete:
        sb.table("lots").delete().eq("id", lot_id).eq("user_id", uid).execute()
    for upd in lots_to_update:
        sb.table("lots").update({"shares": upd["shares"]}).eq("id", upd["id"]).eq("user_id", uid).execute()

    if realized_entries:
        sb.table("realized_trades").insert(realized_entries).execute()

    return realized_entries, None


def load_realized() -> list[dict]:
    """Gibt alle realisierten Trades zurück (neueste zuerst)."""
    return _fetch_realized()


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


def evaluate_positions() -> list[dict]:
    """
    Lädt alle offenen Lots, gruppiert nach Ticker, berechnet P&L und Exit-Signale.
    Output-Schema identisch zur alten JSON-Version, damit app.py und history.py
    unverändert bleiben.
    """
    lots = _fetch_lots()
    eurusd = get_eurusd_rate()

    # Marktumfeld einmalig abrufen
    market_bearish = False
    try:
        from analyzer.market_filter import check_market
        mkt = check_market()
        market_bearish = not mkt.get("passed", True) or mkt.get("warning", False)
    except Exception:
        pass

    # Lots nach Ticker gruppieren
    grouped: dict[str, list[dict]] = {}
    for lot in lots:
        t = lot["ticker"]
        grouped.setdefault(t, []).append(lot)

    # Kursdaten gebündelt laden; Einzelcall bleibt als Fallback je Ticker
    hist_batch = _batch_history(list(grouped))

    results = []
    for ticker, ticker_lots in grouped.items():
        total_shares = _total_shares_from_lots(ticker_lots)
        avg_entry_eur = _avg_price_from_lots(ticker_lots)
        earliest_dt = _earliest_date_from_lots(ticker_lots)
        days_held = (date.today() - earliest_dt).days if earliest_dt else None
        company_name = ticker_lots[0].get("company_name", ticker)
        sector = ticker_lots[0].get("sector")

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
                try:
                    sector = yf.Ticker(ticker).info.get("sector")
                    if sector:
                        # Sektor im ersten Lot cachen
                        get_supabase().table("lots").update({"sector": sector}).eq(
                            "user_id", _uid()
                        ).eq("ticker", ticker).execute()
                except Exception:
                    pass
        except Exception:
            pass

        pnl_abs_eur = None
        pnl_pct = None
        # avg_entry_eur == 0 möglich (z.B. Migration mit fehlendem Kaufkurs) → kein P&L statt Crash
        if avg_entry_eur and current_price_eur is not None:
            pnl_abs_eur = round((current_price_eur - avg_entry_eur) * total_shares, 2)
            pnl_pct = round((current_price_eur / avg_entry_eur - 1) * 100, 2)

        # Lots ins alte Format konvertieren (app.py erwartet 'date' und 'price_eur')
        lots_compat = [
            {
                "id": l["id"],
                "date": l["buy_date"],
                "shares": l["shares"],
                "price_eur": l["price_eur"],
                "notes": l.get("notes", ""),
            }
            for l in sorted(ticker_lots, key=lambda x: x["buy_date"])
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
