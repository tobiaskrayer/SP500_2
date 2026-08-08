"""
Einmaliges Rettungs-Skript: Exportiert die Portfolio-Daten aus Supabase nach
data/portfolio.json — als letzter Schritt vor dem Wechsel weg von Supabase.

Verwendung (im Projekt-Root, NACHDEM das Supabase-Projekt reaktiviert wurde):
    python scripts/export_portfolio_from_supabase.py

Voraussetzungen:
    - .streamlit/secrets.toml mit SUPABASE_URL und SUPABASE_ANON_KEY
    - Supabase-Projekt ist entpausiert (Dashboard → Restore)
    - requests installiert (pip install requests)

Das Skript fragt Email/Passwort des Portfolio-Accounts ab, lädt alle eigenen
Zeilen aus 'lots' und 'realized_trades' und schreibt sie im Format, das
portfolio/manager.py (Git/JSON-Version) erwartet: {"positions": [...], "realized": [...]}.
"""

import json
import os
import sys
import getpass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    import requests
except ImportError:
    print("requests nicht installiert. Bitte: pip install requests")
    sys.exit(1)


def load_secrets() -> tuple[str, str]:
    secrets_path = os.path.join(os.path.dirname(__file__), "..", ".streamlit", "secrets.toml")
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                tomllib = None
                with open(secrets_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SUPABASE_URL"):
                            url = line.split("=", 1)[1].strip().strip('"')
                        elif line.startswith("SUPABASE_ANON_KEY"):
                            key = line.split("=", 1)[1].strip().strip('"')

        if tomllib is not None:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
            url = url or secrets.get("SUPABASE_URL", "")
            key = key or secrets.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL oder SUPABASE_ANON_KEY nicht gefunden.")
    return url, key


def supabase_login(url: str, key: str, email: str, password: str) -> tuple[str, str]:
    res = requests.post(
        f"{url}/auth/v1/token?grant_type=password",
        headers={"apikey": key, "Content-Type": "application/json"},
        json={"email": email, "password": password},
        timeout=15,
    )
    if res.status_code != 200:
        raise RuntimeError(f"Login fehlgeschlagen ({res.status_code}): {res.text}")
    data = res.json()
    return data["access_token"], data["user"]["id"]


def supabase_select(url: str, key: str, token: str, table: str, user_id: str) -> list:
    res = requests.get(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params={"user_id": f"eq.{user_id}", "select": "*"},
        timeout=15,
    )
    res.raise_for_status()
    return res.json()


def rows_to_portfolio(lot_rows: list, trade_rows: list) -> dict:
    """Baut das data/portfolio.json-Zielformat: {"positions": [...], "realized": [...]}."""
    # Lots nach Ticker gruppieren -> eine "position" pro Ticker mit lots[]
    by_ticker: dict[str, dict] = {}
    for row in lot_rows:
        ticker = row.get("ticker", "").upper()
        pos = by_ticker.setdefault(ticker, {
            "ticker": ticker,
            "company_name": row.get("company_name", ticker),
            "sector": row.get("sector"),
            "lots": [],
        })
        pos["lots"].append({
            "id": row.get("id"),
            "date": row.get("buy_date", ""),
            "shares": float(row.get("shares", 0)),
            "price_eur": float(row.get("price_eur", 0)),
            "notes": row.get("notes", ""),
        })

    positions = list(by_ticker.values())

    realized = []
    for row in trade_rows:
        realized.append({
            "id": row.get("id"),
            "ticker": row.get("ticker", "").upper(),
            "company_name": row.get("company_name", ""),
            "buy_date": row.get("buy_date", ""),
            "sell_date": row.get("sell_date", ""),
            "shares": float(row.get("shares", 0)),
            "buy_price_eur": float(row.get("buy_price_eur", 0)),
            "sell_price_eur": float(row.get("sell_price_eur", 0)),
            "pnl_eur": row.get("pnl_eur"),
            "pnl_pct": row.get("pnl_pct"),
            "days_held": row.get("days_held"),
            "notes": row.get("notes", ""),
        })

    return {"positions": positions, "realized": realized}


def main():
    print("=== Portfolio-Rettung: Supabase → data/portfolio.json ===\n")
    print("Voraussetzung: Projekt wurde im Supabase-Dashboard reaktiviert (Restore).\n")

    try:
        url, anon_key = load_secrets()
        print(f"Supabase-URL: {url}\n")
    except Exception as e:
        print(f"Fehler beim Laden der Credentials: {e}")
        sys.exit(1)

    # Zugangsdaten bevorzugt aus Umgebungsvariablen (für nicht-interaktive Läufe),
    # sonst interaktiv abfragen.
    email = os.environ.get("SB_PORTFOLIO_EMAIL", "").strip()
    password = os.environ.get("SB_PORTFOLIO_PASSWORD", "")
    if not email:
        email = input("Email (Supabase-Account): ").strip()
    if not password:
        password = getpass.getpass("Passwort: ")

    try:
        token, user_id = supabase_login(url, anon_key, email, password)
        print(f"\nEingeloggt als: {email} (ID: {user_id})\n")
    except Exception as e:
        print(f"Login fehlgeschlagen: {e}")
        sys.exit(1)

    try:
        lot_rows = supabase_select(url, anon_key, token, "lots", user_id)
        trade_rows = supabase_select(url, anon_key, token, "realized_trades", user_id)
    except Exception as e:
        print(f"Fehler beim Abrufen der Daten: {e}")
        sys.exit(1)

    print(f"Gefunden: {len(lot_rows)} offene Lots, {len(trade_rows)} realisierte Trades.\n")
    for row in lot_rows:
        print(f"  Lot: {row.get('ticker')} — {row.get('buy_date')} "
              f"{float(row.get('shares',0)):g} Stück @ €{float(row.get('price_eur',0)):.2f}")
    for row in trade_rows:
        print(f"  Trade: {row.get('ticker')} — Verkauf {row.get('sell_date')} "
              f"P&L €{(row.get('pnl_eur') or 0):+.2f}")

    portfolio = rows_to_portfolio(lot_rows, trade_rows)

    out_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "portfolio.json")

    if os.path.exists(out_path):
        confirm = input(f"\n{out_path} existiert bereits. Überschreiben? (ja/nein): ").strip().lower()
        if confirm != "ja":
            print("Abgebrochen — keine Datei geschrieben.")
            sys.exit(0)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Geschrieben: {out_path}")
    print(f"   {len(portfolio['positions'])} Positionen, {len(portfolio['realized'])} realisierte Trades.")
    print("\nNächster Schritt: Datei prüfen, dann committen:")
    print("  git add data/portfolio.json")
    print("  git commit -m 'Portfolio-Daten aus Supabase exportiert'")


if __name__ == "__main__":
    main()
