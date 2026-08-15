"""Empfehlungs-Log in Monats-Shards (history/logger)."""
import json
import os

import pytest

from history import logger as lg


@pytest.fixture
def log_dir(tmp_path, monkeypatch):
    """Leitet Shard-Verzeichnis und Alt-Datei auf tmp um."""
    shards = tmp_path / "log"
    shards.mkdir()
    monkeypatch.setattr(lg, "SHARD_DIR", str(shards))
    monkeypatch.setattr(lg, "LEGACY_LOG_FILE", str(tmp_path / "recommendations_log.json"))
    return shards


def _result(date_str: str, ticker: str = "AAPL") -> dict:
    """Minimales run_full_scan-Ergebnis fuer append_scan_result."""
    return {
        "timestamp": f"{date_str}T21:35:00",
        "market": {"vix": 15.0, "sp500_price": 5000.0,
                   "sp500_above_ma50": True, "sp500_above_ma200": True},
        "recommendations": [{
            "ticker": ticker, "price": 100.0, "sector": "Technology",
            "combined_score": 0.9, "confidence_label": "Strong Buy",
            "tech": {"score": 0.83, "signals": {}, "indicators": {}},
            "fund": {"score": 0.7, "signals": {}, "metrics": {}},
            "rs": {"rs_3m": 5.0, "rs_6m": 8.0},
            "upside": {"expected_upside_pct": 12.0, "upside_label": "Mittel"},
        }],
        "recommendations_v2": [{"ticker": ticker, "price": 100.0, "v2_rank": 1,
                                "rs": {"rs_3m": 5.0, "rs_6m": 8.0}}],
    }


def test_append_creates_monthly_shard(log_dir):
    lg.append_scan_result(_result("2026-08-07"))

    assert (log_dir / "2026-08.json").exists()
    assert not (log_dir / "2026-07.json").exists()


def test_same_month_lands_in_one_shard(log_dir):
    lg.append_scan_result(_result("2026-08-05"))
    lg.append_scan_result(_result("2026-08-07"))

    assert os.listdir(log_dir) == ["2026-08.json"]
    assert [e["date"] for e in lg.load_log()] == ["2026-08-05", "2026-08-07"]


def test_new_month_leaves_old_shard_byte_identical(log_dir):
    """Der Kern des Sharding-Gewinns: abgeschlossene Monate werden nie wieder angefasst."""
    lg.append_scan_result(_result("2026-07-31"))
    july_before = (log_dir / "2026-07.json").read_bytes()

    lg.append_scan_result(_result("2026-08-03"))

    assert (log_dir / "2026-07.json").read_bytes() == july_before
    assert (log_dir / "2026-08.json").exists()


def test_same_date_replaces_instead_of_duplicating(log_dir):
    lg.append_scan_result(_result("2026-08-07", ticker="AAPL"))
    lg.append_scan_result(_result("2026-08-07", ticker="MSFT"))

    log = lg.load_log()
    assert len(log) == 1
    assert log[0]["recommendations"][0]["ticker"] == "MSFT"


def test_load_log_merges_shards_in_date_order(log_dir):
    lg.append_scan_result(_result("2026-08-03"))
    lg.append_scan_result(_result("2026-06-15"))
    lg.append_scan_result(_result("2026-07-01"))

    assert [e["date"] for e in lg.load_log()] == ["2026-06-15", "2026-07-01", "2026-08-03"]


def test_load_log_merges_legacy_monolith(log_dir):
    """Nicht migrierte Checkouts muessen weiterlaufen."""
    with open(lg.LEGACY_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([{"date": "2026-05-07", "recommendations": []}], f)
    lg.append_scan_result(_result("2026-08-07"))

    assert [e["date"] for e in lg.load_log()] == ["2026-05-07", "2026-08-07"]


def test_shard_wins_over_legacy_on_duplicate_date(log_dir):
    with open(lg.LEGACY_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump([{"date": "2026-08-07", "recommendations": [{"ticker": "ALT"}]}], f)
    lg.append_scan_result(_result("2026-08-07", ticker="NEU"))

    log = lg.load_log()
    assert len(log) == 1
    assert log[0]["recommendations"][0]["ticker"] == "NEU"


def test_shards_are_written_compact(log_dir):
    lg.append_scan_result(_result("2026-08-07"))
    raw = (log_dir / "2026-08.json").read_text(encoding="utf-8")

    assert "\n" not in raw, "indent=2 kostet ~38 % Bytes in jedem Tages-Commit"


def test_fingerprint_changes_after_append(log_dir):
    lg.append_scan_result(_result("2026-08-05"))
    before = lg.log_fingerprint()

    lg.append_scan_result(_result("2026-08-07"))

    assert lg.log_fingerprint() != before, "st.cache_data wuerde nicht invalidieren"


def test_fingerprint_stable_without_change(log_dir):
    lg.append_scan_result(_result("2026-08-07"))
    assert lg.log_fingerprint() == lg.log_fingerprint()


def test_migration_round_trip(log_dir, monkeypatch):
    """Monolith ueber 2 Monate -> 2 Shards -> load_log() liefert dasselbe."""
    original = [
        {"date": "2026-07-15", "recommendations": [{"ticker": "AAPL"}]},
        {"date": "2026-07-31", "recommendations": [{"ticker": "MSFT"}]},
        {"date": "2026-08-03", "recommendations": [{"ticker": "NVDA"}]},
    ]
    with open(lg.LEGACY_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(original, f)

    from scripts import migrate_recommendations_log as mig
    monkeypatch.setattr(mig, "SHARD_DIR", lg.SHARD_DIR)
    monkeypatch.setattr(mig, "LEGACY_LOG_FILE", lg.LEGACY_LOG_FILE)
    assert mig.main() == 0

    assert sorted(os.listdir(log_dir)) == ["2026-07.json", "2026-08.json"]
    assert lg.load_log() == original

    # Idempotent: zweiter Lauf aendert nichts
    before = {n: (log_dir / n).read_bytes() for n in os.listdir(log_dir)}
    assert mig.main() == 0
    assert {n: (log_dir / n).read_bytes() for n in os.listdir(log_dir)} == before
