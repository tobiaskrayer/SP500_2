"""Portfolio-Persistenz lokal und via GitHub-API (portfolio/github_store)."""
import base64
import json

import pytest

from portfolio import github_store as gs


# ── Lokaler Modus ─────────────────────────────────────────────────────────────

@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "_LOCAL_PATH", str(tmp_path / "data" / "portfolio.json"))
    monkeypatch.setattr(gs, "is_cloud", lambda: False)
    return tmp_path


def test_local_round_trip(local):
    payload = {"positions": [{"ticker": "AAPL", "lots": []}], "realized": []}
    gs.save(payload, None, "Test")

    data, sha = gs.load()
    assert data == payload
    assert sha is None, "lokal gibt es keinen SHA"


def test_local_missing_file_returns_empty(local):
    data, sha = gs.load()
    assert data == {"positions": [], "realized": []}
    assert sha is None


def test_local_defaults_missing_keys(local):
    path = local / "data"
    path.mkdir()
    (path / "portfolio.json").write_text('{"positions": []}', encoding="utf-8")

    data, _sha = gs.load()
    assert data["realized"] == [], "fehlender realized-Key muss ergaenzt werden"


# ── Cloud-Modus (GitHub Contents-API) ─────────────────────────────────────────

class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeRequests:
    def __init__(self, get_response=None, put_response=None):
        self._get, self._put = get_response, put_response
        self.put_body = None

    def get(self, url, **kwargs):
        return self._get

    def put(self, url, **kwargs):
        self.put_body = kwargs.get("json")
        return self._put


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("IS_STREAMLIT_CLOUD", "1")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    monkeypatch.delenv("GITHUB_BRANCH", raising=False)
    # st.secrets darf lokal nicht dazwischenfunken
    monkeypatch.setattr(gs, "_secret", lambda name, default="": {
        "GITHUB_TOKEN": "tok", "GITHUB_REPO": "o/r", "GITHUB_BRANCH": "main",
    }.get(name, default))
    assert gs.is_cloud()


def _content_response(payload: dict, sha: str = "abc123"):
    encoded = base64.b64encode(json.dumps(payload).encode()).decode()
    return _Response(200, {"content": encoded, "sha": sha})


def test_cloud_load_decodes_content_and_sha(cloud, monkeypatch):
    payload = {"positions": [{"ticker": "MSFT"}], "realized": []}
    monkeypatch.setattr(gs, "requests", _FakeRequests(get_response=_content_response(payload)))

    data, sha = gs.load()
    assert data == payload
    assert sha == "abc123"


def test_cloud_load_404_returns_empty_without_sha(cloud, monkeypatch):
    monkeypatch.setattr(gs, "requests", _FakeRequests(get_response=_Response(404)))

    data, sha = gs.load()
    assert data == {"positions": [], "realized": []}
    assert sha is None


def test_cloud_save_sends_sha_in_body(cloud, monkeypatch):
    fake = _FakeRequests(put_response=_Response(200))
    monkeypatch.setattr(gs, "requests", fake)

    gs.save({"positions": [], "realized": []}, "sha-xyz", "Portfolio: Kauf")

    assert fake.put_body["sha"] == "sha-xyz", "ohne SHA ueberschreibt der Commit blind"
    assert fake.put_body["message"] == "Portfolio: Kauf"
    assert fake.put_body["branch"] == "main"
    decoded = json.loads(base64.b64decode(fake.put_body["content"]).decode())
    assert decoded == {"positions": [], "realized": []}


def test_cloud_save_omits_sha_for_new_file(cloud, monkeypatch):
    fake = _FakeRequests(put_response=_Response(201))
    monkeypatch.setattr(gs, "requests", fake)

    gs.save({"positions": [], "realized": []}, None, "Neu")

    assert "sha" not in fake.put_body


def test_cloud_save_conflict_raises_conflict_error(cloud, monkeypatch):
    monkeypatch.setattr(gs, "requests", _FakeRequests(put_response=_Response(409)))

    with pytest.raises(gs.ConflictError):
        gs.save({"positions": [], "realized": []}, "alt", "Test")


def test_cloud_save_other_error_raises_runtime_error(cloud, monkeypatch):
    monkeypatch.setattr(gs, "requests",
                        _FakeRequests(put_response=_Response(422, text="Unprocessable")))

    with pytest.raises(RuntimeError) as exc:
        gs.save({"positions": [], "realized": []}, "alt", "Test")
    assert not isinstance(exc.value, gs.ConflictError)
    assert "422" in str(exc.value)


def test_cloud_without_token_raises(monkeypatch):
    monkeypatch.setenv("IS_STREAMLIT_CLOUD", "1")
    monkeypatch.setattr(gs, "_secret", lambda name, default="": default)

    with pytest.raises(RuntimeError) as exc:
        gs.load()
    assert "GITHUB_TOKEN" in str(exc.value)
