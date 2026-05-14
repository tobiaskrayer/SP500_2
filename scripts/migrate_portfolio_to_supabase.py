"""
Einmaliges Migrations-Skript: Importiert portfolio.json in Supabase.
Verwendet die Supabase REST-API direkt (kein supabase-Paket nötig).

Verwendung (im Projekt-Root):
    python scripts/migrate_portfolio_to_supabase.py

Voraussetzungen:
    - .streamlit/secrets.toml mit SUPABASE_URL und SUPABASE_ANON_KEY
    - portfolio.json im Projekt-Root vorhanden
    - Tabellen 'lots' und 'realized_trades' in Supabase angelegt
    - requests installiert (pip install requests)
"""

import json
import os
import sys
import getpass

# Projekt-Root zum Suchpfad hinzufügen
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
                # Einfaches TOML-Parsing ohne externe Bibliothek
                with open(secrets_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("SUPABASE_URL"):
                            url = line.split("=", 1)[1].strip().strip('"')
                        elif line.startswith("SUPABASE_ANON_KEY"):
                            key = line.split("=", 1)[1].strip().strip('"')
                tomllib = None

        if tomllib is not None:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
            url = url or secrets.get("SUPABASE_URL", "")
            key = key or secrets.get("SUPABASE_ANON_KEY", "")

    if not url or not key:
        raise RuntimeError("SUPABASE_URL oder SUPABASE_ANON_KEY nicht gefunden.")
    return url, key


def supabase_login(url: str, key: str, email: str, password: str) -> str:
    """Gibt den Access-Token zurück."""
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


def supabase_select(url: str, key: str, token: str, table: str, params: dict = None) -> list:
    res = requests.get(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params=params or {},
        timeout=15,
    )
    res.raise_for_status()
    return res.json()


def supabase_insert(url: str, key: str, token: str, table: str, rows: list) -> None:
    res = requests.post(
        f"{url}/rest/v1/{table}",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        },
        json=rows,
        timeout=30,
    )
    if res.status_code not in (200, 201):
        raise RuntimeError(f"Insert in {table} fehlgeschlagen ({res.status_code}): {res.text}")


def load_portfolio_json() -> dict:
    portfolio_path = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")
    if not os.path.exists(portfolio_path):
        raise FileNotFoundError(f"portfolio.json nicht gefunden: {portfolio_path}")
    with open(portfolio_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    print("=== Portfolio-Migration: portfolio.json → Supabase ===\n")

    try:
        url, anon_key = load_secrets()
        print(f"Supabase-URL: {url}\n")
    except Exception as e:
        print(f"Fehler beim Laden der Credentials: {e}")
        sys.exit(1)

    email = input("Email (Supabase-Account): ").strip()
    password = getpass.getpass("Passwort: ")

    try:
        token, user_id = supabase_login(url, anon_key, email, password)
        print(f"\nEingeloggt als: {email} (ID: {user_id})\n")
    except Exception as e:
        print(f"Login fehlgeschlagen: {e}")
        sys.exit(1)

    # Prüfen ob bereits Daten vorhanden
    try:
        existing = supabase_select(url, anon_key, token, "lots",
                                   {"user_id": f"eq.{user_id}", "limit": "1"})
        if existing:
            print("⚠️  Dieser Account hat bereits Lots in Supabase.")
            confirm = input("Trotzdem fortfahren und weitere Daten hinzufügen? (ja/nein): ").strip().lower()
            if confirm != "ja":
                print("Abgebrochen.")
                sys.exit(0)
    except Exception as e:
        print(f"Warnung beim Prüfen bestehender Daten: {e}")

    try:
        data = load_portfolio_json()
    except Exception as e:
        print(f"Fehler beim Laden von portfolio.json: {e}")
        sys.exit(1)

    positions = data.get("positions", [])
    realized = data.get("realized", [])

    # Lots migrieren
    lot_rows = []
    for pos in positions:
        ticker = pos.get("ticker", "").upper()
        company_name = pos.get("company_name", ticker)
        sector = pos.get("sector")

        if "lots" not in pos:
            lots = [{
                "date": pos.get("entry_date", ""),
                "shares": pos.get("shares", 0),
                "price_eur": pos.get("entry_price_eur") or pos.get("entry_price") or 0,
                "notes": pos.get("notes", ""),
            }]
        else:
            lots = pos["lots"]

        for lot in lots:
            lot_rows.append({
                "user_id": user_id,
                "ticker": ticker,
                "company_name": company_name,
                "sector": sector,
                "buy_date": lot.get("date", ""),
                "shares": float(lot.get("shares", 0)),
                "price_eur": float(lot.get("price_eur", 0)),
                "notes": lot.get("notes", ""),
            })
            print(f"  Lot: {ticker} — {lot.get('date')} {float(lot.get('shares',0)):g} Stück @ €{float(lot.get('price_eur',0)):.2f}")

    if lot_rows:
        supabase_insert(url, anon_key, token, "lots", lot_rows)
        print(f"\n✅ {len(lot_rows)} Lots eingefügt.")
    else:
        print("Keine offenen Positionen in portfolio.json.")

    # Realisierte Trades migrieren
    trade_rows = []
    for trade in realized:
        trade_rows.append({
            "user_id": user_id,
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
        print(f"  Trade: {trade.get('ticker','').upper()} — Verkauf {trade.get('sell_date')} P&L €{trade.get('pnl_eur', 0):+.2f}")

    if trade_rows:
        supabase_insert(url, anon_key, token, "realized_trades", trade_rows)
        print(f"\n✅ {len(trade_rows)} realisierte Trades eingefügt.")
    else:
        print("Keine realisierten Trades in portfolio.json.")

    print("\n=== Migration abgeschlossen ===")
    print("Nächster Schritt: portfolio.json aus dem Repo entfernen:")
    print("  git rm portfolio.json")
    print("  echo portfolio.json >> .gitignore   (ist bereits drin)")


if __name__ == "__main__":
    main()
