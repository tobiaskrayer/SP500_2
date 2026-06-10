"""Mini-Test: Top-N-Logik in scorer._apply_rs_percentile."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer.scorer import _apply_rs_percentile

# 20 fiktive Ergebnisse, alle bestehen Trend/Overbought/Fund — rs_score 1..20
results = []
for i in range(1, 21):
    results.append({
        "ticker": f"T{i:02d}",
        "rs": {"rs_score": float(i), "rs_6m": 1.0},
        "gate_tech": True, "gate_fund": True,
        "trend_ok": True, "not_overbought": True,
    })

out = _apply_rs_percentile(results, market={})
v2 = sorted((r for r in out if r["recommended_v2"]), key=lambda x: x["v2_rank"])
print("v2-Empfehlungen:", len(v2))
for r in v2:
    print(f"  Rang {r['v2_rank']}: {r['ticker']} rs={r['rs']['rs_score']}")

assert v2[0]["ticker"] == "T20" and v2[0]["v2_rank"] == 1, "Rang 1 falsch"
assert all(r["v2_rank"] <= 10 for r in v2), "Rang > top_n"
assert all(r["v2_rank"] is None for r in out if not r.get("recommended_v2")), \
    "Nicht-Empfohlene duerfen keinen Rang haben"

# Grenzfall: mehr als 10 Survivors -> harte Kappung auf 10
results2 = []
for i in range(1, 101):
    results2.append({
        "ticker": f"S{i:03d}",
        "rs": {"rs_score": float(i), "rs_6m": 1.0},
        "gate_tech": True, "gate_fund": True,
        "trend_ok": True, "not_overbought": True,
    })
out2 = _apply_rs_percentile(results2, market={})
v2_2 = [r for r in out2 if r["recommended_v2"]]
print("Survivors bei 100 Titeln (top20% = 20, gekappt auf 10):", len(v2_2))
assert len(v2_2) == 10, f"Erwartet 10, bekommen {len(v2_2)}"
ranks = sorted(r["v2_rank"] for r in v2_2)
assert ranks == list(range(1, 11)), f"Raenge nicht 1..10: {ranks}"
# Die 10 hoechsten Scores (91..100) muessen es sein
tks = {r["ticker"] for r in v2_2}
assert tks == {f"S{i:03d}" for i in range(91, 101)}, "Falsche Titel im Top-10"

print("ALLE CHECKS OK")
