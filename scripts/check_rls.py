"""
Prüft, ob Row-Level-Security auf den Portfolio-Tabellen wirkt.

Test: anonymer REST-Zugriff (nur ANON_KEY, kein Login) auf lots und
realized_trades — read-only, verändert nichts.

  - RLS AKTIV:  PostgREST liefert 200 + leeres Array (keine Policy für anon)
  - RLS FEHLT:  PostgREST liefert die Zeilen ALLER Nutzer -> Datenleck

Ein leeres Ergebnis kann theoretisch auch eine leere Tabelle bedeuten —
bei befülltem Portfolio ist der Test aussagekräftig.

Ausführen:  python -X utf8 scripts/check_rls.py
Fix:        scripts/supabase_rls.sql im Supabase SQL-Editor ausführen.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from scripts.migrate_portfolio_to_supabase import load_secrets


def main():
    url, key = load_secrets()
    print(f"Supabase: {url}\n")

    leak = False
    for table in ("lots", "realized_trades"):
        res = requests.get(
            f"{url}/rest/v1/{table}",
            headers={"apikey": key, "Accept": "application/json"},
            params={"select": "user_id", "limit": "5"},
            timeout=15,
        )
        if res.status_code in (401, 403):
            print(f"  {table:18} -> HTTP {res.status_code}: anon geblockt (RLS aktiv)")
            continue
        if res.status_code != 200:
            print(f"  {table:18} -> HTTP {res.status_code}: {res.text[:120]}")
            continue
        rows = res.json()
        if rows:
            users = {r.get("user_id") for r in rows}
            print(f"  {table:18} -> ⚠️  {len(rows)}+ Zeilen ANONYM lesbar "
                  f"({len(users)} Nutzer-IDs) — RLS FEHLT!")
            leak = True
        else:
            print(f"  {table:18} -> 0 Zeilen anonym sichtbar (RLS aktiv oder Tabelle leer)")

    print()
    if leak:
        print("ERGEBNIS: Datenleck — scripts/supabase_rls.sql im SQL-Editor ausführen!")
        sys.exit(1)
    print("ERGEBNIS: Kein anonymer Zugriff möglich.")
    print("Hinweis: Der Test deckt den Anon-Fall ab. Dass ein EINGELOGGTER Nutzer")
    print("fremde Zeilen nicht sieht, garantiert nur RLS — im Dashboard unter")
    print("Database -> Tables pruefen, dass bei lots/realized_trades 'RLS enabled' steht.")


if __name__ == "__main__":
    main()
