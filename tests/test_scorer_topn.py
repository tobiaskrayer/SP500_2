"""Top-N-Ranking des v2-Algorithmus (scorer._apply_rs_percentile)."""
from analyzer.scorer import _apply_rs_percentile


def _make_results(n):
    return [{
        "ticker": f"T{i:03d}",
        "rs": {"rs_score": float(i), "rs_6m": 1.0},
        "gate_tech": True, "gate_fund": True,
        "trend_ok": True, "not_overbought": True,
    } for i in range(1, n + 1)]


def test_ranking_order_and_rank_one_is_strongest():
    out = _apply_rs_percentile(_make_results(20), market={})
    v2 = sorted((r for r in out if r["recommended_v2"]), key=lambda x: x["v2_rank"])
    assert v2[0]["ticker"] == "T020" and v2[0]["v2_rank"] == 1
    scores = [r["rs"]["rs_score"] for r in v2]
    assert scores == sorted(scores, reverse=True)


def test_cap_at_top_n():
    # 100 Titel -> top20% = 20 Survivors -> harte Kappung auf 10
    out = _apply_rs_percentile(_make_results(100), market={})
    v2 = [r for r in out if r["recommended_v2"]]
    assert len(v2) == 10
    assert sorted(r["v2_rank"] for r in v2) == list(range(1, 11))
    assert {r["ticker"] for r in v2} == {f"T{i:03d}" for i in range(91, 101)}


def test_non_recommended_have_no_rank():
    out = _apply_rs_percentile(_make_results(100), market={})
    assert all(r["v2_rank"] is None for r in out if not r["recommended_v2"])
