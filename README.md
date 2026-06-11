# S&P500-Analysetool

Streamlit-App, die täglich alle ~503 S&P500-Titel durch ein 4-stufiges
Gate-System schickt und Kaufkandidaten für eine Haltedauer von 1–8 Wochen
priorisiert. Mit Portfolio-Tracking (Supabase, mehrbenutzerfähig),
Performance-Nachverfolgung und einem 10-Jahres-Backtest, der die eigene
Empfehlungslogik validiert.

> **Keine Anlageberatung.** Der gemessene Edge ist statistisch, moderat und
> trägt Survivorship-Bias (siehe [backtest/FINDINGS.md](backtest/FINDINGS.md)).

## Die 4 Gates

| Gate | Modul | Prüft |
|---|---|---|
| 1 — Markt | `analyzer/market_filter.py` | VIX (3-Tage-Mittel), S&P500 über 50/200-Tage-MA. Rot → keine Empfehlungen. |
| 2 — Relative Stärke | `analyzer/relative_strength.py` | 3M+6M-Outperformance vs. S&P500, Perzentil-Ranking übers Universum. **Das einzige Signal mit nachgewiesener Vorhersagekraft.** |
| 3 — Technik | `analyzer/technical.py` | MA50/200, RSI, MACD, Bollinger, Volumen (6 Signale, Score-Schwelle 70 %). |
| 4 — Fundamentals | `analyzer/fundamental.py` | KGV, Umsatzwachstum, Marge, Verschuldung, FCF (Score-Schwelle 60 %). |

Zwei Empfehlungslisten laufen parallel:

- **v1**: alle vier Gates klassisch (Tech-Score-Schwelle, RS top 33 %).
- **v2**: datengetrieben aus dem Backtest — RS top 20 %, Trend + „nicht
  überkauft" als harte Filter statt Tech-Score, begrenzt auf die **Top 10**
  nach RS-Score (⭐ = Top 5). Hintergründe in [backtest/FINDINGS.md](backtest/FINDINGS.md).

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

Für Portfolio/Login wird ein Supabase-Projekt benötigt — Credentials in
`.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://<projekt>.supabase.co"
SUPABASE_ANON_KEY = "<anon-key>"
```

Erwartete Tabellen: `lots` (offene Kauf-Lots) und `realized_trades`
(abgeschlossene Trades), jeweils mit `user_id`-Spalte.
**Wichtig bei mehreren Nutzern:** Auf beiden Tabellen Row-Level-Security
aktivieren mit Policies `user_id = auth.uid()` — die App filtert zwar
klientseitig, aber nur RLS erzwingt die Isolation serverseitig.

## Betrieb / Datenflüsse

- **GitHub Actions** ([daily_analysis.yml](.github/workflows/daily_analysis.yml))
  scannt werktags um 21:30 UTC und committed die Ergebnisse ins Repo
  (`cache/results_<datum>.json`, History-Logs, Fundamentals-Seed). Die
  deployte App (Streamlit Cloud) zieht den Commit und zeigt die Daten ohne
  eigenen Scan.
- **Caches** (alle regenerierbar): Kurs-Tages-Cache (`cache/prices/`,
  gitignored), Fundamentals-Cache mit 3-Tage-TTL (`cache/fundamentals.json`,
  gitignored; git-getrackter Seed wärmt ihn nach Deploys vor),
  S&P500-Universum-Fallback (`cache/sp500_universe.json`).
- **Scan-Dauer:** Erster Lauf des Tages lädt Kurse (~1–2 min), danach
  Sekunden (warme Caches).

## Backtest & Analyse-Tools

```bash
python -m backtest.compare 10            # A/B v1 vs v2 über 10 Jahre
python -m backtest.diagnostics           # Schwachstellen-Report
python -m backtest.stop_sim              # Stop-Loss-Simulation (OHLC-Pfade)
python -m scripts.experiment_filters     # 21 Filter-Varianten vergleichen
```

Kernbefunde (Details in [backtest/FINDINGS.md](backtest/FINDINGS.md)):
Der Tech-Score rankt nicht; der Edge lebt im obersten RS-Bereich und skaliert
mit Konzentration (Top-10); enge ATR-Stops zerstören mehr Rendite als sie
schützen — Risikokontrolle über Korbbreite und Markt-Gate.

## Tests

```bash
pytest tests/ -q
```

Netzwerkfreie Regressions-Suite (läuft bei jedem Push via
[tests.yml](.github/workflows/tests.yml)). Zusätzliche manuelle Smoke-Tests
mit Netzwerk liegen in `scripts/test_*.py`.

## Projektstruktur

```
app.py                  Streamlit-UI (Seiten, Charts, Navigation)
config.py               Alle Schwellenwerte & Parameter, zentral dokumentiert
scheduler.py            Tages-Cache, Hintergrund-Scan, Serialisierung
run_analysis.py         Headless-Scan für GitHub Actions
analyzer/               Gates 1-4, Scorer, Indikatoren, Caches, Universum
backtest/               Runner, A/B-Vergleich, Stop-Simulation, FINDINGS.md
portfolio/              Supabase-Auth, Lots/Trades, Portfolio-History
history/                Empfehlungs-Log + Performance-Nachverfolgung
tests/                  pytest-Regressionssuite (netzwerkfrei)
scripts/                Experimente, Migrations- und Smoke-Test-Skripte
```
