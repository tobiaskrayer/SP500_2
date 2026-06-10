# 10-Jahres-Backtest: Befunde & v2-Algorithmus

Empirische Auswertung der aktuellen Empfehlungslogik über 10 Jahre (2016–2026),
volles S&P-500-Universum (503 Titel, heutige Zusammensetzung), Scan alle 2 Wochen.
**7448 messbare v1-Trades, 7755 v2-Trades.** Reproduzierbar via:

```
python -m backtest.diagnostics          # Schwachstellen-Report (liest cache/backtest/results.json)
python -m backtest.compare 10           # A/B v1 vs v2
```

> ⚠️ **Survivorship-Bias:** Das Universum ist die *heutige* Index-Zusammensetzung.
> Über 10 Jahre rückwärts werden also die heutigen Gewinner getestet → alle absoluten
> Zahlen sind eher optimistisch. Für den **relativen** v1-vs-v2-Vergleich ist das
> unkritisch, da beide demselben Bias unterliegen.
> **Gate 4 (Fundamentals)** ist nicht backtestbar (yfinance liefert keine historischen
> Snapshots) — Backtest und v2-Validierung betreffen die Gates 1–3.

## Ergebnis aktuelle Logik (v1)

| Kennzahl | Wert |
|---|---|
| Ø Return 1M | +1,45 % |
| Trefferquote 1M | 57,6 % |
| Ø vs SPY 1M | +0,57 % |
| Sharpe 1M | 0,14 |
| Ø Return 3M | +4,46 % |

Fazit: echter, aber **moderater** Edge. Der Mehrwert kommt fast ausschließlich aus
der Korb-Diversifikation — Einzeltitel schlagen SPY nur knapp über 50 %.

## Schwachstellen

1. **Gate 3 (Tech-Score) hat keine Vorhersagekraft.** Titel mit perfektem Score
   (6/6 Signale) liefen mit +0,31 % vs SPY *schlechter* als 5/6 (+0,54 %). Die
   Score-Abstufung rankt nicht; „alle 6 Signale" zu fordern ist sogar kontraproduktiv.
2. **Gate 2 (RS) ist das einzige echte Signal — der Schnitt ist zu locker.** Nach
   RS-Quartil: Q1–Q3 praktisch flach (+0,16 bis +0,28 % vs SPY), nur das oberste
   Quartil springt auf **+1,40 %** und 59,9 % Trefferquote. Der Edge lebt in den
   Top ~15–25 %, nicht in den Top 33 %.
3. **Unkontrolliertes Tail-Risiko.** Die schlimmsten Trades waren
   hochvolatile/parabolische Momentum-Namen sowie Crash-Vorabende (2020-02).
   Entry-Filter (Vola-Deckel, Anti-Parabel) fangen dieses Gap-Risiko **nicht** —
   das ist Aufgabe der Stop-/Exit-Logik (im Backtest nicht modelliert).

## v2-Algorithmus (datengetrieben)

Hebel-Isolation über 8 Varianten (`backtest/compare.py`) ergab als beste Konfiguration:

- **RS-Schnitt auf Top 20 %** verschärfen (Befund 2). Monoton besser bis ~15 %;
  20 % hält die Streubreite nahe v1 (~43 Picks/Datum).
- **Trend-Pflicht** (über MA50 UND MA200) und **nicht überkauft** (RSI ≤ 70, unter
  oberem BB-Band) als *harte* Strukturfilter statt der wirkungslosen Tech-Score-Schwelle
  (Befund 1).
- **Gate 1 + Gate 4 unverändert.**
- Vola-/Parabel-Deckel **verworfen** — im Test wirkungslos bis schädlich (Befund 3).

### A/B-Ergebnis (10 Jahre, identische Daten)

| Kennzahl | v1 | v2 | Δ |
|---|---|---|---|
| n (Trades) | 7448 | 7755 | |
| Ø vs SPY 1M | +0,57 % | **+0,65 %** | +14 % |
| Trefferquote 1M | 57,6 % | 57,4 % | ≈ gleich |
| Sharpe 1M | 0,14 | **0,15** | +7 % |
| Ø Return 1M | +1,45 % | **+1,66 %** | |
| Ø Return 3M | +4,46 % | **+5,04 %** | |

v2 zeigt einen kleinen, konsistenten Vorteil in absoluten Returns und vs-SPY-Outperformance.
Der Sharpe-Unterschied ist gering (0,14 → 0,15); die Trefferquote ist praktisch gleich.
Der wesentliche Mehrwert von v2 liegt im **höheren absoluten Return** bei ähnlichem Risiko,
nicht in einer dramatically besseren Trefferquote.

> **Hinweis:** Diese Zahlen wurden mit dem korrigierten `_forward_return` (B1-Fix:
> erster Handelstag ≥ Zieldatum statt letzter ≤ Zieldatum+5) und korrekter bt_dates-
> Generierung ermittelt. Frühere Versionen des Backtests enthielten beide Fehler und
> lieferten andere absolute Werte (v1: +1,64 % / Sharpe 0,16; v2: +0,90 % vs SPY).

## Live-Integration

v2 läuft **parallel** im Scanner ([analyzer/scorer.py](../analyzer/scorer.py)):
jede Aktie bekommt zusätzlich ein `recommended_v2`-Flag, `run_full_scan` liefert eine
separate `recommendations_v2`-Liste. Die Empfehlungsseite zeigt beide nebeneinander
(Überschneidung v1∩v2). v1-Empfehlungen bleiben unverändert. Parameter in
[config.py](../config.py) → `RECOMMENDER_V2`.

### Offen / nächste Schritte
- **Forward-Tracking:** v2-Empfehlungen ins History-Log schreiben, um v1 vs v2 auch
  *live* (out-of-sample) zu vergleichen — der ehrlichste Test ohne Survivorship-Bias.
- **Stop-Logik im Backtest** modellieren, um den Tail-Effekt der Exit-Signale zu messen.
