"""
Aggregationen über angereicherte Empfehlungsdaten.
Alle Funktionen nehmen die flache Liste aus performance.enrich_with_performance().
"""

from collections import defaultdict

# Winsorisierungs-Grenze für robuste Mittelwerte: die extremsten 2,5 % an jedem Rand
# werden auf das Quantil geklemmt. So kann ein einzelnes Ereignis (Split-Artefakt,
# Crash, Moonshot) den Ø nicht mehr kippen — der Median ist ohnehin extremwert-robust.
WINSOR_LIMIT = 0.025


def summary_stats(recs: list[dict]) -> dict:
    """Gesamtüberblick: n, Trefferquote, Ø/Median Performance, robuster Ø."""
    measurable = [r for r in recs if r.get("performance_1m") is not None]
    if not measurable:
        return {"total": len(recs), "measurable": 0}
    hits = sum(1 for r in measurable if r.get("hit_1m"))
    perfs = [r["performance_1m"] for r in measurable]
    vs_spy = [r["perf_vs_spy_1m"] for r in measurable if r.get("perf_vs_spy_1m") is not None]
    return {
        "total": len(recs),
        "measurable": len(measurable),
        "hit_rate": round(hits / len(measurable) * 100, 1),
        "avg_perf_1m": round(sum(perfs) / len(perfs), 2),
        "avg_perf_1m_robust": _winsor_mean(perfs),
        "median_perf_1m": _median(perfs),
        "avg_vs_spy_1m": round(sum(vs_spy) / len(vs_spy), 2) if vs_spy else None,
        "median_vs_spy_1m": _median(vs_spy) if vs_spy else None,
        # Wie viele auswertbare Einträge lagen in einem Split-/Adjustment-Fenster?
        # (Rendite ist seit dem Fix korrekt, aber der Anteil gehört in den Report,
        #  damit ein Einzelereignis nie wieder unbemerkt die Kennzahlen verschiebt.)
        "n_split_rebased": sum(1 for r in measurable if r.get("split_rebased")),
        "best": max(measurable, key=lambda r: r["performance_1m"]),
        "worst": min(measurable, key=lambda r: r["performance_1m"]),
    }


def by_confidence(recs: list[dict]) -> list[dict]:
    """Hit-Rate und Ø Performance je Konfidenz-Label."""
    groups = defaultdict(list)
    for r in recs:
        if r.get("performance_1m") is not None:
            label = r.get("confidence_label") or "Unbekannt"
            groups[label].append(r)

    result = []
    for label in ["Strong Buy", "Moderate Buy", "Watch", "Unbekannt"]:
        grp = groups.get(label, [])
        if not grp:
            continue
        hits = sum(1 for r in grp if r.get("hit_1m"))
        perfs = [r["performance_1m"] for r in grp]
        vs_spy = [r["perf_vs_spy_1m"] for r in grp if r.get("perf_vs_spy_1m") is not None]
        result.append({
            "label": label,
            "n": len(grp),
            "hit_rate": round(hits / len(grp) * 100, 1),
            "avg_perf": round(sum(perfs) / len(perfs), 2),
            "median_perf": _median(perfs),
            "avg_vs_spy": round(sum(vs_spy) / len(vs_spy), 2) if vs_spy else None,
        })
    return result


def signal_effectiveness(recs: list[dict], signal_type: str = "tech") -> list[dict]:
    """
    Für jeden Einzelsignal: Ø Performance wenn aktiv vs. wenn inaktiv.
    signal_type: "tech" oder "fund"
    """
    field = "tech_signals" if signal_type == "tech" else "fund_signals"
    measurable = [r for r in recs if r.get("performance_1m") is not None and r.get(field)]

    if not measurable:
        return []

    # Alle Signalnamen sammeln
    all_signals = set()
    for r in measurable:
        all_signals.update(r[field].keys())

    result = []
    for signal in sorted(all_signals):
        active = [r for r in measurable if r[field].get(signal)]
        inactive = [r for r in measurable if not r[field].get(signal)]

        avg_active = _avg_perf(active)
        avg_inactive = _avg_perf(inactive)
        delta = round(avg_active - avg_inactive, 2) if (avg_active is not None and avg_inactive is not None) else None

        result.append({
            "signal": signal,
            "active_n": len(active),
            "active_avg_perf": avg_active,
            "active_hit_rate": _hit_rate(active),
            "inactive_n": len(inactive),
            "inactive_avg_perf": avg_inactive,
            "delta": delta,
        })

    # Sortierung: größtes Delta zuerst
    result.sort(key=lambda x: x["delta"] if x["delta"] is not None else 0, reverse=True)
    return result


def by_sector(recs: list[dict]) -> list[dict]:
    """Ø Performance und Hit-Rate je Sektor."""
    groups = defaultdict(list)
    for r in recs:
        if r.get("performance_1m") is not None:
            sector = r.get("sector") or "Unbekannt"
            groups[sector].append(r)

    result = []
    for sector, grp in sorted(groups.items()):
        perfs = [r["performance_1m"] for r in grp]
        result.append({
            "sector": sector,
            "n": len(grp),
            "avg_perf": round(sum(perfs) / len(perfs), 2),
            "median_perf": _median(perfs),
            "hit_rate": round(sum(1 for r in grp if r.get("hit_1m")) / len(grp) * 100, 1),
        })
    result.sort(key=lambda x: x["avg_perf"], reverse=True)
    return result


def by_vix(recs: list[dict]) -> list[dict]:
    """Performance je VIX-Bucket."""
    buckets = {"< 15": [], "15–20": [], "> 20": []}
    for r in recs:
        if r.get("performance_1m") is None:
            continue
        vix = (r.get("market_context") or {}).get("vix")
        if vix is None:
            continue
        if vix < 15:
            buckets["< 15"].append(r)
        elif vix <= 20:
            buckets["15–20"].append(r)
        else:
            buckets["> 20"].append(r)

    result = []
    for label, grp in buckets.items():
        if not grp:
            continue
        perfs = [r["performance_1m"] for r in grp]
        result.append({
            "vix_bucket": label,
            "n": len(grp),
            "avg_perf": round(sum(perfs) / len(perfs), 2),
            "hit_rate": round(sum(1 for r in grp if r.get("hit_1m")) / len(grp) * 100, 1),
        })
    return result


def by_upside_label(recs: list[dict]) -> list[dict]:
    """Hit-Rate und Ø Performance je Upside-Label."""
    groups = defaultdict(list)
    for r in recs:
        if r.get("performance_1m") is not None:
            label = r.get("upside_label") or "Unbekannt"
            groups[label].append(r)

    result = []
    for label in ["Hoch", "Mittel", "Gering", "Unbekannt"]:
        grp = groups.get(label, [])
        if not grp:
            continue
        hits = sum(1 for r in grp if r.get("hit_1m"))
        perfs = [r["performance_1m"] for r in grp]
        vs_spy = [r["perf_vs_spy_1m"] for r in grp if r.get("perf_vs_spy_1m") is not None]
        result.append({
            "label": label,
            "n": len(grp),
            "hit_rate": round(hits / len(grp) * 100, 1),
            "avg_perf": round(sum(perfs) / len(perfs), 2),
            "median_perf": _median(perfs),
            "avg_vs_spy": round(sum(vs_spy) / len(vs_spy), 2) if vs_spy else None,
        })
    return result


def worst_recommendations(recs: list[dict], n: int = 10) -> list[dict]:
    """Die n schlechtesten Empfehlungen mit vollständigem Signal-Pattern."""
    measurable = [r for r in recs if r.get("performance_1m") is not None]
    return sorted(measurable, key=lambda r: r["performance_1m"])[:n]


def best_recommendations(recs: list[dict], n: int = 10) -> list[dict]:
    """Die n besten Empfehlungen."""
    measurable = [r for r in recs if r.get("performance_1m") is not None]
    return sorted(measurable, key=lambda r: r["performance_1m"], reverse=True)[:n]


def _avg_perf(recs: list[dict]):
    perfs = [r["performance_1m"] for r in recs if r.get("performance_1m") is not None]
    return round(sum(perfs) / len(perfs), 2) if perfs else None


def _median(values):
    """Extremwert-robuster Median; None bei leerer Eingabe."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    mid = len(vals) // 2
    med = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    return round(med, 2)


def _winsor_mean(values, limit: float = WINSOR_LIMIT):
    """Mittelwert nach Winsorisierung: die extremsten `limit` an jedem Rand werden
    auf das jeweilige Quantil geklemmt. Unter 5 Werten = normaler Mittelwert (zu
    wenig Daten, um Extremwerte sinnvoll zu klemmen)."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    if len(vals) >= 5:
        lo = vals[int(limit * (len(vals) - 1))]
        hi = vals[int((1 - limit) * (len(vals) - 1))]
        vals = [min(max(v, lo), hi) for v in vals]
    return round(sum(vals) / len(vals), 2)


def _hit_rate(recs: list[dict]):
    if not recs:
        return None
    return round(sum(1 for r in recs if r.get("hit_1m")) / len(recs) * 100, 1)
