# S&P500-Analysetool

Streamlit-App, die täglich alle ~503 S&P500-Titel durch ein 4-stufiges
Gate-System schickt und Kaufkandidaten für eine Haltedauer von 1–8 Wochen
priorisiert. Mit Portfolio-Tracking (Ein-Nutzer, Passwort-Gate, Git/JSON-Storage),
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

Lokal läuft die App ohne jede Konfiguration. Das Portfolio liegt versioniert in
[data/portfolio.json](data/portfolio.json) und wird direkt als Datei geschrieben;
Committen/Pushen macht man wie gewohnt selbst.

Optional in `.streamlit/secrets.toml` (gitignored):

```toml
# Passwort-Gate. Nicht gesetzt = App offen (praktisch lokal).
PORTFOLIO_PASSWORD = "<passwort>"

# Nur für das Deployment auf Streamlit Cloud: dort kann git zur Laufzeit nicht
# schreiben, deshalb committet die App data/portfolio.json über die GitHub
# Contents-API. Siehe portfolio/github_store.py.
GITHUB_TOKEN  = "<fine-grained PAT mit contents:write>"
GITHUB_REPO   = "tobiaskrayer/SP500_2"   # Default
GITHUB_BRANCH = "main"                    # Default
```

Tests brauchen zusätzlich `pip install -r requirements-dev.txt`.

## Betrieb / Datenflüsse

- **GitHub Actions** ([daily_analysis.yml](.github/workflows/daily_analysis.yml))
  scannt werktags um 21:30 UTC und committed die Ergebnisse ins Repo. Die
  deployte App (Streamlit Cloud) zieht den Commit und zeigt die Daten ohne
  eigenen Scan.
- **Was der tägliche Job committet** — bewusst kurz gehalten, denn jede Datei
  landet für immer in der Git-Historie:

  | Datei | Größe | Zweck |
  |---|---|---|
  | `cache/results_latest.json` | ~1,1 MB | Der letzte Scan. **Fester Dateiname**, kein Datum: der Job läuft nur Mo–Fr, ein datierter Name ließe die App am Wochenende leer aussehen. |
  | `history/log/<YYYY-MM>.json` | ≤ 0,8 MB | Empfehlungs-Log, monatlich geschnitten. Abgeschlossene Monate ändern sich nie wieder → genau ein Blob pro Monat. |
  | `cache/fundamentals_seed.json` | ~67 KB | Wärmt den `Ticker.info`-Cache nach jedem Deploy vor. |
  | `cache/sp500_universe.json` | ~14 KB | Letzte gute Tickerliste (Wikipedia-Fallback). |

  Der Job addiert diese Pfade **explizit** (kein `git add cache/`), damit keine
  Laufzeit-Artefakte hineinrutschen.
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
app.py                  Streamlit-Shell (Navigation, Seiten-Dispatch)
views/                  Eine Datei pro Seite (Charts, Tabellen, Formulare)
config.py               Alle Schwellenwerte & Parameter, zentral dokumentiert
storage.py              Atomares JSON-Schreiben (tmp + os.replace)
scheduler.py            Tages-Cache, Hintergrund-Scan, Serialisierung
run_analysis.py         Headless-Scan für GitHub Actions
analyzer/               Gates 1-4, Scorer, Indikatoren, Caches, Universum
backtest/               Runner, A/B-Vergleich, Stop-Simulation, FINDINGS.md
portfolio/              Passwort-Gate, Lots/Trades, GitHub-Storage, History
history/                Empfehlungs-Log (log/) + Performance-Nachverfolgung
tests/                  pytest-Regressionssuite (netzwerkfrei)
scripts/                Experimente, Migrations- und Smoke-Test-Skripte
```
