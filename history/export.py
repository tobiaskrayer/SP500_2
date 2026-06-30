"""
Export-Generator: erzeugt einen Markdown-Report für Claude und ein Roh-JSON.
"""

import json
import os
from datetime import date

from history.analytics import (
    summary_stats, by_confidence, signal_effectiveness,
    by_sector, by_vix, worst_recommendations, best_recommendations,
    by_upside_label,
)


def _pct(value) -> str:
    """Score (0–1) als Prozent — robust gegen fehlende UND None-Werte.

    `r.get(key, 0)` schützt nur gegen fehlende Keys; ein vorhandener None-Wert
    (z. B. bei Empfehlungen ohne berechneten Score) ergäbe sonst None*100 → TypeError.
    """
    return f"{(value or 0) * 100:.0f}%"


def generate_markdown_report(enriched_recs: list[dict]) -> str:
    """
    Generiert einen Markdown-Report, der direkt an Claude gegeben werden kann,
    um Verbesserungsvorschläge für config.py und die Gate-Logik zu erhalten.
    """
    today = str(date.today())
    stats = summary_stats(enriched_recs)
    conf_data = by_confidence(enriched_recs)
    upside_data = by_upside_label(enriched_recs)
    tech_sigs = signal_effectiveness(enriched_recs, "tech")
    fund_sigs = signal_effectiveness(enriched_recs, "fund")
    sectors = by_sector(enriched_recs)
    vix_data = by_vix(enriched_recs)
    worst = worst_recommendations(enriched_recs, 10)
    best = best_recommendations(enriched_recs, 5)

    lines = []

    lines += [
        f"# S&P500 Analyse — Performance-Report für Code-Verbesserung",
        f"**Stand:** {today}",
        "",
        "---",
        "",
        "## 1. Gesamtübersicht",
        "",
        f"- **Gesamtempfehlungen im Log:** {stats['total']}",
        f"- **Davon auswertbar (≥30 Tage):** {stats['measurable']}",
    ]

    if stats.get("measurable", 0) > 0:
        lines += [
            f"- **Trefferquote 1M (positiv):** {stats['hit_rate']}%",
            f"- **Ø Performance 1M:** {stats['avg_perf_1m']:+.1f}%",
        ]
        # Median + winsorisierter Ø: weichen sie stark vom rohen Ø ab, dominieren
        # Extremwerte (z. B. ein Split-/Crash-Ereignis) die Kennzahl. Der Median ist
        # die robustere Schätzung der typischen Empfehlung.
        if stats.get("median_perf_1m") is not None:
            lines.append(f"- **Median Performance 1M:** {stats['median_perf_1m']:+.1f}%")
        if stats.get("avg_perf_1m_robust") is not None:
            lines.append(f"- **Ø Performance 1M (winsorisiert):** {stats['avg_perf_1m_robust']:+.1f}%")
        if stats.get("avg_vs_spy_1m") is not None:
            lines.append(f"- **vs. SPY (Outperformance 1M):** {stats['avg_vs_spy_1m']:+.1f}%")
        if stats.get("median_vs_spy_1m") is not None:
            lines.append(f"- **vs. SPY (Median 1M):** {stats['median_vs_spy_1m']:+.1f}%")
        if stats.get("n_split_rebased"):
            lines.append(
                f"- **⚠️ Split-/Adjustment-Fenster:** {stats['n_split_rebased']} auswertbare "
                f"Einträge lagen in einem Split-/Dividendenfenster (Rendite split-konsistent "
                f"gerechnet; Roh-Einstiegspreis weicht stark vom adjustierten Kurs ab)."
            )
        if stats.get("best"):
            b = stats["best"]
            lines.append(f"- **Beste Empfehlung:** {b['ticker']} ({b['rec_date']}) → {b['performance_1m']:+.1f}%")
        if stats.get("worst"):
            w = stats["worst"]
            lines.append(f"- **Schlechteste Empfehlung:** {w['ticker']} ({w['rec_date']}) → {w['performance_1m']:+.1f}%")
    else:
        lines.append("- Noch keine Empfehlungen mit ≥30 Tagen Haltedauer — Performance-Daten kommen mit der Zeit.")

    lines += ["", "---", ""]

    # Konfidenz-Kalibrierung
    lines += ["## 2. Konfidenz-Kalibrierung", ""]
    if conf_data:
        lines.append("| Label | n | Hit-Rate | Ø Perf 1M | Median 1M | vs SPY |")
        lines.append("|---|---|---|---|---|---|")
        for c in conf_data:
            vs = f"{c['avg_vs_spy']:+.1f}%" if c.get("avg_vs_spy") is not None else "N/A"
            med = f"{c['median_perf']:+.1f}%" if c.get("median_perf") is not None else "N/A"
            lines.append(f"| {c['label']} | {c['n']} | {c['hit_rate']}% | {c['avg_perf']:+.1f}% | {med} | {vs} |")
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += [
        "",
        "**Interpretation:** Wenn 'Strong Buy' nicht besser performt als 'Moderate Buy', sind die Konfidenz-Schwellen (aktuell: Strong ≥ 85%, Moderate ≥ 70%) zu überdenken.",
        "", "---", "",
    ]

    # Upside-Validierung
    lines += ["## 2b. Upside-Validierung", ""]
    lines.append("Validiert, ob das berechnete erwartete Upside (ATR + 52w-Hoch + Wachstum) mit der tatsächlichen Performance korreliert.")
    lines.append("")
    if upside_data:
        lines.append("| Upside-Label | n | Hit-Rate | Ø Perf 1M | Median 1M | vs SPY |")
        lines.append("|---|---|---|---|---|---|")
        for u in upside_data:
            vs = f"{u['avg_vs_spy']:+.1f}%" if u.get("avg_vs_spy") is not None else "N/A"
            med = f"{u['median_perf']:+.1f}%" if u.get("median_perf") is not None else "N/A"
            lines.append(f"| {u['label']} | {u['n']} | {u['hit_rate']}% | {u['avg_perf']:+.1f}% | {med} | {vs} |")
    else:
        lines.append("_Noch keine auswertbaren Daten._")
    lines += [
        "",
        "**Interpretation:** Wenn 'Hoch' nicht deutlich besser performt als 'Gering', sollten die Gewichte in `config.UPSIDE` angepasst werden.",
        "", "---", "",
    ]

    # Tech-Signal-Wirksamkeit
    lines += ["## 3. Signal-Wirksamkeit — Technische Analyse", ""]
    if tech_sigs:
        lines.append("| Signal | Aktiv (n) | Ø Perf aktiv | Inaktiv (n) | Ø Perf inaktiv | Delta |")
        lines.append("|---|---|---|---|---|---|")
        for s in tech_sigs:
            delta_str = f"{s['delta']:+.1f}%" if s["delta"] is not None else "N/A"
            warn = " ⚠️" if (s["delta"] is not None and s["delta"] < 0) else ""
            lines.append(
                f"| {s['signal']} | {s['active_n']} | "
                f"{s['active_avg_perf']:+.1f}% | {s['inactive_n']} | "
                f"{s['inactive_avg_perf']:+.1f}% | {delta_str}{warn} |"
                if (s.get("active_avg_perf") is not None and s.get("inactive_avg_perf") is not None)
                else f"| {s['signal']} | {s['active_n']} | N/A | {s['inactive_n']} | N/A | N/A |"
            )
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += [
        "",
        "**Hinweis:** Signale mit negativem Delta (⚠️) erhöhen die Trefferquote NICHT — möglicherweise Kandidaten zur Entfernung oder Anpassung.",
        "", "---", "",
    ]

    # Fund-Signal-Wirksamkeit
    lines += ["## 4. Signal-Wirksamkeit — Fundamentalanalyse", ""]
    if fund_sigs:
        lines.append("| Signal | Aktiv (n) | Ø Perf aktiv | Inaktiv (n) | Ø Perf inaktiv | Delta |")
        lines.append("|---|---|---|---|---|---|")
        for s in fund_sigs:
            delta_str = f"{s['delta']:+.1f}%" if s["delta"] is not None else "N/A"
            warn = " ⚠️" if (s["delta"] is not None and s["delta"] < 0) else ""
            lines.append(
                f"| {s['signal']} | {s['active_n']} | "
                f"{s['active_avg_perf']:+.1f}% | {s['inactive_n']} | "
                f"{s['inactive_avg_perf']:+.1f}% | {delta_str}{warn} |"
                if (s.get("active_avg_perf") is not None and s.get("inactive_avg_perf") is not None)
                else f"| {s['signal']} | {s['active_n']} | N/A | {s['inactive_n']} | N/A | N/A |"
            )
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += ["", "---", ""]

    # Sektor-Performance
    lines += ["## 5. Performance je Sektor", ""]
    if sectors:
        lines.append("| Sektor | n | Ø Perf 1M | Median 1M | Hit-Rate |")
        lines.append("|---|---|---|---|---|")
        for s in sectors:
            med = f"{s['median_perf']:+.1f}%" if s.get("median_perf") is not None else "N/A"
            lines.append(f"| {s['sector']} | {s['n']} | {s['avg_perf']:+.1f}% | {med} | {s['hit_rate']}% |")
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += ["", "---", ""]

    # VIX-Kontext
    lines += ["## 6. Performance je Markt-Volatilität (VIX)", ""]
    if vix_data:
        lines.append("| VIX-Bereich | n | Ø Perf 1M | Hit-Rate |")
        lines.append("|---|---|---|---|")
        for v in vix_data:
            lines.append(f"| {v['vix_bucket']} | {v['n']} | {v['avg_perf']:+.1f}% | {v['hit_rate']}% |")
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += ["", "---", ""]

    # Beste und schlechteste Empfehlungen
    lines += ["## 7. Pattern-Analyse — schlechteste Empfehlungen", ""]
    if worst:
        lines.append("Diese Positionen haben am schlechtesten abgeschnitten. Bitte auf gemeinsame Signal-Muster achten.")
        lines.append("")
        for r in worst:
            lines.append(f"### {r['ticker']} ({r['rec_date']}) → {r['performance_1m']:+.1f}%")
            lines.append(f"- Konfidenz: {r.get('confidence_label','—')} (Score: {_pct(r.get('combined_score'))})")
            lines.append(f"- Tech-Score: {_pct(r.get('tech_score'))} | Fund-Score: {_pct(r.get('fund_score'))}")
            lines.append(f"- RS 3M: {r.get('rs_3m','N/A')}% | RS 6M: {r.get('rs_6m','N/A')}%")
            lines.append(f"- Sektor: {r.get('sector','N/A')}")
            lines.append(f"- Markt-VIX zum Zeitpunkt: {(r.get('market_context') or {}).get('vix','N/A')}")
            tech_sigs_r = r.get("tech_signals", {})
            if tech_sigs_r:
                active = [k for k, v in tech_sigs_r.items() if v]
                inactive = [k for k, v in tech_sigs_r.items() if not v]
                lines.append(f"- Tech aktiv: {', '.join(active) or '—'}")
                lines.append(f"- Tech inaktiv: {', '.join(inactive) or '—'}")
            ind = r.get("indicators", {})
            if ind.get("rsi"):
                lines.append(f"- RSI: {ind['rsi']} | BB-Position: {ind.get('bb_pct','N/A')}%")
            met = r.get("metrics", {})
            if met.get("pe"):
                lines.append(f"- KGV: {met['pe']} | Marge: {met.get('profit_margin','N/A')} | Wachstum: {met.get('revenue_growth','N/A')}")
            lines.append("")
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    lines += ["---", ""]
    lines += ["## 8. Pattern-Analyse — beste Empfehlungen", ""]
    if best:
        for r in best:
            lines.append(f"### {r['ticker']} ({r['rec_date']}) → {r['performance_1m']:+.1f}%")
            lines.append(f"- Konfidenz: {r.get('confidence_label','—')} | Tech: {_pct(r.get('tech_score'))} | Fund: {_pct(r.get('fund_score'))}")
            lines.append(f"- Sektor: {r.get('sector','N/A')} | VIX: {(r.get('market_context') or {}).get('vix','N/A')}")
            lines.append("")
    else:
        lines.append("_Noch keine auswertbaren Daten._")

    # Aktuelle Konfiguration
    lines += ["---", "", "## 9. Aktuelle Konfiguration (config.py)", ""]
    config_path = os.path.join(os.path.dirname(__file__), "..", "config.py")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines.append("```python")
            lines.append(f.read())
            lines.append("```")
    except Exception:
        lines.append("_config.py konnte nicht geladen werden._")

    lines += [
        "", "---", "",
        "## Auftrag für Claude",
        "",
        "Bitte analysiere die obigen Performance-Daten und beantworte folgende Fragen:",
        "",
        "1. **Konfidenz-Schwellen:** Sind die Schwellen für 'Strong Buy' (≥85%) und 'Moderate Buy' (≥70%) in `config.py` korrekt kalibriert? Welche Werte wären basierend auf den Daten besser?",
        "2. **Signal-Wirksamkeit:** Welche Tech- und Fund-Signale haben ein negatives oder schwaches Delta und könnten angepasst oder entfernt werden?",
        "3. **Sektor-Bias:** Gibt es Sektoren, die systematisch schlecht performen und aus dem Universum ausgeschlossen werden sollten?",
        "4. **Markt-Filter:** Zeigen die VIX-Daten, dass die aktuelle `vix_stop`-Schwelle (25) zu hoch oder zu niedrig ist?",
        "5. **Upside-Kalibrierung:** Korreliert das berechnete erwartete Upside ('Hoch'/'Mittel'/'Gering') mit der tatsächlichen Performance? Welche Gewichte in `config.UPSIDE` wären besser?",
        "6. **Konservativität:** Sind die Gate-Schwellen (`min_score` für Tech ≥70%, Fundamentals ≥60%) angemessen — oder sollten sie verschärft oder gelockert werden?",
        "7. **Sonstige Verbesserungen:** Was fällt dir in den Daten noch auf, das auf eine systematische Schwäche hindeutet?",
        "",
        "Bitte gib **konkrete Vorschläge** in Form von geänderten `config.py`-Werten oder Code-Änderungen.",
    ]

    return "\n".join(lines)


def generate_json_export(enriched_recs: list[dict]) -> str:
    """Gibt die angereicherten Rohdaten als JSON-String zurück."""
    safe = []
    for r in enriched_recs:
        safe.append({k: v for k, v in r.items() if isinstance(v, (str, int, float, bool, dict, list, type(None)))})
    return json.dumps(safe, indent=2, ensure_ascii=False)
