# 10-Jahres-Backtest: Befunde & v2-Algorithmus

Empirische Auswertung der aktuellen Empfehlungslogik über 10 Jahre (2016–2026),
volles S&P-500-Universum (503 Titel, heutige Zusammensetzung), Scan alle 2 Wochen.
Reproduzierbar via:

```
python -m backtest.diagnostics          # Schwachstellen-Report (liest cache/backtest/results.json)
python -m backtest.compare 10           # A/B v1 vs v2
python -m scripts.experiment_filters    # Filter-Varianten-Vergleich (21 Varianten)
python -m backtest.stop_sim             # Stop-Loss-Simulation (OHLC-Pfade)
```

> ⚠️ **Survivorship-Bias:** Das Universum ist die *heutige* Index-Zusammensetzung.
> Über 10 Jahre rückwärts werden also die heutigen Gewinner getestet → alle absoluten
> Zahlen sind eher optimistisch. Für den **relativen** v1-vs-v2-Vergleich ist das
> unkritisch, da beide demselben Bias unterliegen — bei starker RS-Konzentration
> (Top-N) verstärkt sich der Bias aber, weil Dekaden-Gewinner (NVDA, AMD, TSLA …)
> die Top-Ränge dominieren. Der ehrliche Test ist das Out-of-Sample-Forward-Tracking.
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

(n = 7448 messbare Trades.) Fazit: echter, aber **moderater** Edge. Der Mehrwert
kommt fast ausschließlich aus der Korb-Diversifikation — Einzeltitel schlagen SPY
nur knapp über 50 %.

## Schwachstellen / Befunde

1. **Gate 3 (Tech-Score) hat keine Vorhersagekraft.** Titel mit perfektem Score
   (6/6 Signale) liefen *schlechter* als 5/6. Die Score-Abstufung rankt nicht;
   „alle 6 Signale" zu fordern ist sogar kontraproduktiv.
2. **Gate 2 (RS) ist das einzige echte Signal — und es skaliert mit Konzentration.**
   Der Edge lebt im obersten RS-Bereich; siehe Befund 4.
3. **Unkontrolliertes Tail-Risiko.** Die schlimmsten Trades waren
   hochvolatile/parabolische Momentum-Namen sowie Crash-Vorabende (2020-02).
   Entry-Filter (Vola-Deckel, Anti-Parabel) fangen dieses Gap-Risiko **nicht**,
   und auch ATR-Stops sind keine Lösung (Befund 5).
4. **Top-N-Konzentration dominiert alle anderen Hebel** (Filter-Experimente,
   `scripts/experiment_filters.py`, 21 Varianten auf identischen Daten):

   | Variante | Ø vs SPY 1M | Median vs SPY | Sharpe | Jahre positiv |
   |---|---|---|---|---|
   | v2-Korb ohne Top-N (~43 Picks) | +0,65 % | −0,05 % | 0,15 | 9/11 |
   | **v2 + Top-10 pro Scan** | **+2,12 %** | **+0,56 %** | **0,21** | **11/11** |
   | v2 + Top-5 pro Scan | +3,19 % | +0,91 % | 0,24 | 11/11 |

   Der Median steigt mit (kein reiner Ausreißer-Effekt), die Top-1%-Konzentration
   am Gesamtertrag *sinkt* (31 % → 23 %). Dagegen **verschlechtern**: Pullback-Filter
   (max X % über MA50), Vola-Caps, Volumen-Bestätigung, Anti-Parabel-Cap.
   MACD als harte Pflicht kostet Rendite (Top-10: +2,12 % → +1,33 %), verbessert
   aber den schlimmsten Trade (−85 % → −53 %) → als **Tiebreaker-Anzeige** sinnvoll,
   nicht als Filter.
5. **ATR-Stops zerstören den Edge** (Stop-Simulation auf OHLC-Pfaden,
   `backtest/stop_sim.py`, v2-Top-10-Trades, Gap-Handling wie echte Stop-Order):

   | Variante (56d-Horizont) | Ø Ret | Median | Hit % | Sharpe | p5 | Worst | gestoppt |
   |---|---|---|---|---|---|---|---|
   | **Halten bis Horizont** | **+6,17 %** | **+3,68 %** | **59,8** | **0,29** | −20,0 | −57,8 | 0 % |
   | Stop 2×ATR, 6%-Cap (Live-Logik) | +2,86 % | −4,41 % | 35,8 | 0,16 | −12,0 | −24,9 | 62 % |
   | Stop + TP 3×ATR (Live-Logik) | +1,22 % | −3,37 % | 46,7 | 0,13 | −12,0 | −24,9 | 97 % |
   | Trailing 2×ATR | +1,39 % | −1,82 % | 40,4 | 0,12 | −9,9 | −24,9 | 97 % |
   | Stop 4×ATR ohne Cap | +5,27 % | +2,35 % | 55,2 | 0,25 | −18,2 | −42,2 | 30 % |
   | Stop 5×ATR ohne Cap | +5,42 % | +3,20 % | 57,7 | 0,25 | −20,7 | −45,1 | 22 % |

   Beim 30d-Horizont dasselbe Bild. Enge Stops (2×ATR mit 6%-Cap ≈ max −12 %)
   reißen bei normaler Momentum-Volatilität, die gestoppten Trades hätten sich
   mehrheitlich erholt. **Kein getesteter Stop verbessert Return oder Sharpe.**
   Konsequenz: Risikokontrolle über **Korbbreite (Gleichgewichtung) + Markt-Gate
   + Zeithorizont**, nicht über enge Einzeltitel-Stops. Ein *weiter*
   Katastrophen-Stop (4–5×ATR, ≈ −20/−30 %) ist als Versicherung vertretbar
   (kostet ~0,8 Pkt. Return, kappt Worst-Case von −58 % auf −42/−45 %).
   Caveat: Survivorship-Bias überzeichnet Erholungen — real fängt ein Stop auch
   Delistings, die im heutigen Universum fehlen. Die Exit-*Signale* der App
   (MACD/RSI/Trailing-Drawdown als Beobachtungs-Hinweise) sind davon unberührt;
   getestet wurde der **mechanische** Stop.

## v2-Algorithmus (datengetrieben)

- **RS-Schnitt Top 20 %** + **Top-10-Kappung** nach RS-Score (Befund 4);
  die ersten 5 werden als ⭐ Top-Pick markiert (stärkste Gruppe).
- **Trend-Pflicht** (über MA50 UND MA200) und **nicht überkauft** (RSI ≤ 70, unter
  oberem BB-Band) als *harte* Strukturfilter statt der wirkungslosen
  Tech-Score-Schwelle (Befund 1).
- **Gate 1 + Gate 4 unverändert.**
- Vola-/Parabel-Deckel, Pullback-Filter, Volumen-Pflicht **verworfen** (Befund 4).
- MACD als **Anzeige** (Tiebreaker), nicht als Filter.

### A/B-Ergebnis (10 Jahre, identische Daten)

| Kennzahl | v1 | v2 (Top-10) |
|---|---|---|
| n (Trades) | 7448 | 1810 |
| Ø vs SPY 1M | +0,57 % | **+2,12 %** |
| Trefferquote 1M | 57,6 % | 58,0 % |
| Sharpe 1M | 0,14 | **0,21** |
| Ø Return 1M | +1,45 % | **+3,15 %** |
| Ø Return 3M | +4,46 % | **+9,68 %** |

> Zahlen mit korrigiertem `_forward_return` (erster Handelstag ≥ Zieldatum) und
> korrekter bt_dates-Generierung. Absolute Werte wegen Survivorship-Bias
> optimistisch — die Top-N-Konzentration verstärkt diesen Effekt (s. o.).

## Live-Integration

v2 läuft **parallel** im Scanner ([analyzer/scorer.py](../analyzer/scorer.py)):
jede Aktie bekommt `recommended_v2` + `v2_rank` (1–10, ⭐ = Rang ≤ 5),
`run_full_scan` liefert eine separate `recommendations_v2`-Liste (max. 10).
Die Kauf-Kandidaten-Seite zeigt v1∩v2 mit Top-5-Markierung, v2-Rang und
MACD-Tiebreaker-Spalte. v1-Empfehlungen bleiben unverändert. Parameter in
[config.py](../config.py) → `RECOMMENDER_V2` (`top_n`, `top_n_strong`).
`v2_rank` und `macd_bull` werden im History-Log mitgeschrieben → erlaubt
Out-of-Sample-Vergleich Top-5 vs. Top-10 vs. voller Korb.

### Offen / nächste Schritte
- **Forward-Tracking auswerten**, sobald genug Out-of-Sample-Daten da sind:
  bestätigt sich der Top-N-Vorsprung ohne Survivorship-Bias?
- Exit-*Signal*-Kombinationen (MACD-bearish-Tage, Trailing-Drawdown 15 %) im
  Backtest testen — der mechanische ATR-Stop ist widerlegt (Befund 5), die
  diskretionären Beobachtungs-Signale sind noch ungetestet.
