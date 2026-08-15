"""FIFO-Verkaufslogik und Lesefreiheit von evaluate_positions (portfolio/manager)."""
import pytest

from portfolio import manager as mgr


@pytest.fixture
def portfolio(monkeypatch):
    """
    In-Memory-Portfolio mit 3 Lots. _save wird aufgezeichnet statt geschrieben —
    so faellt jeder ungewollte Schreibvorgang auf.
    """
    data = {
        "positions": [{
            "ticker": "AAPL",
            "company_name": "Apple Inc.",
            "sector": "Technology",
            "lots": [
                {"id": "l1", "date": "2026-01-10", "shares": 10.0, "price_eur": 100.0, "notes": ""},
                {"id": "l2", "date": "2026-02-20", "shares": 5.0, "price_eur": 120.0, "notes": ""},
                {"id": "l3", "date": "2026-03-30", "shares": 5.0, "price_eur": 140.0, "notes": ""},
            ],
        }],
        "realized": [],
    }
    saves = []
    monkeypatch.setattr(mgr, "_load", lambda: (data, None))
    monkeypatch.setattr(mgr, "_save", lambda d, sha, msg: saves.append(msg))
    return data, saves


def test_fifo_consumes_oldest_lot_first(portfolio):
    data, saves = portfolio

    entries, err = mgr.sell_position("AAPL", 6.0, 200.0, "2026-06-01")

    assert err is None
    assert len(entries) == 1
    e = entries[0]
    assert e["buy_date"] == "2026-01-10", "aeltestes Lot muss zuerst verkauft werden"
    assert e["buy_price_eur"] == 100.0
    assert e["shares"] == 6.0
    assert e["pnl_eur"] == round((200.0 - 100.0) * 6.0, 2)
    assert e["pnl_pct"] == 100.0
    assert e["days_held"] == 142

    lots = {l["id"]: l["shares"] for l in data["positions"][0]["lots"]}
    assert lots == {"l1": 4.0, "l2": 5.0, "l3": 5.0}
    assert len(saves) == 1


def test_sale_spanning_two_lots_splits_per_lot(portfolio):
    data, _ = portfolio

    entries, err = mgr.sell_position("AAPL", 13.0, 200.0, "2026-06-01")

    assert err is None
    assert len(entries) == 2, "je Lot ein realized-Eintrag mit eigenem Einstandskurs"
    assert [e["shares"] for e in entries] == [10.0, 3.0]
    assert [e["buy_price_eur"] for e in entries] == [100.0, 120.0]
    assert [e["buy_date"] for e in entries] == ["2026-01-10", "2026-02-20"]
    # P&L je Lot getrennt, nicht ueber einen Mischkurs
    assert entries[0]["pnl_eur"] == 1000.0
    assert entries[1]["pnl_eur"] == 240.0

    lots = {l["id"]: l["shares"] for l in data["positions"][0]["lots"]}
    assert lots == {"l2": 2.0, "l3": 5.0}, "vollstaendig verkauftes Lot muss weg sein"


def test_full_sale_removes_position(portfolio):
    data, _ = portfolio

    entries, err = mgr.sell_position("AAPL", 20.0, 200.0, "2026-06-01")

    assert err is None
    assert len(entries) == 3
    assert data["positions"] == [], "Position ohne Lots muss entfernt werden"
    assert len(data["realized"]) == 3


def test_tiny_float_residue_deletes_lot(monkeypatch):
    """0.3 von 0.3 verkaufen darf kein 1e-17-Restlot hinterlassen."""
    data = {
        "positions": [{
            "ticker": "AAPL", "company_name": "Apple", "sector": None,
            "lots": [
                {"id": "l1", "date": "2026-01-10", "shares": 0.3, "price_eur": 100.0, "notes": ""},
                {"id": "l2", "date": "2026-02-10", "shares": 1.0, "price_eur": 100.0, "notes": ""},
            ],
        }],
        "realized": [],
    }
    monkeypatch.setattr(mgr, "_load", lambda: (data, None))
    monkeypatch.setattr(mgr, "_save", lambda d, sha, msg: None)

    _entries, err = mgr.sell_position("AAPL", 0.3, 200.0, "2026-06-01")

    assert err is None
    assert [l["id"] for l in data["positions"][0]["lots"]] == ["l2"]


@pytest.mark.parametrize("shares,price,sell_date,fragment", [
    (0.0,   200.0, "2026-06-01", "groesser als 0"),
    (-5.0,  200.0, "2026-06-01", "groesser als 0"),
    (25.0,  200.0, "2026-06-01", "vorhanden"),
    (5.0,     0.0, "2026-06-01", "Verkaufskurs"),
    (5.0,  200.0,  "01.06.2026", "Ungueltiges Datum"),
    (5.0,  200.0,  "2099-01-01", "Zukunft"),
    (5.0,  200.0,  "2025-01-01", "fruehesten Kaufdatum"),
])
def test_invalid_sales_are_rejected_without_saving(portfolio, shares, price, sell_date, fragment):
    data, saves = portfolio
    lots_before = [dict(l) for l in data["positions"][0]["lots"]]

    entries, err = mgr.sell_position("AAPL", shares, price, sell_date)

    assert entries == []
    assert err is not None
    # Umlaute im Fehlertext umgehen: nur auf ASCII-Kern pruefen
    normalized = (err.replace("ü", "ue").replace("ä", "ae")
                     .replace("ö", "oe").replace("ß", "ss"))
    assert fragment in normalized, f"unerwartete Meldung: {err}"
    assert saves == [], "abgelehnter Verkauf darf nicht speichern"
    assert data["positions"][0]["lots"] == lots_before


def test_unknown_ticker_is_rejected(portfolio):
    _data, saves = portfolio
    entries, err = mgr.sell_position("MSFT", 1.0, 200.0, "2026-06-01")
    assert entries == [] and "nicht gefunden" in err
    assert saves == []


def test_evaluate_positions_never_writes(portfolio, monkeypatch):
    """
    Regressionsschutz: evaluate_positions ist LESEND. Auf Streamlit Cloud waere
    jeder Schreibvorgang ein GitHub-Commit, ausgeloest durch blosses Ansehen.
    """
    _data, _saves = portfolio

    def _explode(*args, **kwargs):
        raise AssertionError("evaluate_positions hat geschrieben!")

    monkeypatch.setattr(mgr, "_save", _explode)
    monkeypatch.setattr(mgr, "_batch_history", lambda tickers, period="3mo": {})
    monkeypatch.setattr(mgr, "get_eurusd_rate", lambda: 1.10)
    monkeypatch.setattr(mgr.yf, "Ticker", lambda t: (_ for _ in ()).throw(RuntimeError("kein Netz")))

    results = mgr.evaluate_positions(market_bearish=False)

    assert len(results) == 1
    assert results[0]["ticker"] == "AAPL"
    assert results[0]["total_shares"] == 20.0
    # gewichteter Einstand: (10*100 + 5*120 + 5*140) / 20
    assert results[0]["avg_entry_price_eur"] == 115.0
