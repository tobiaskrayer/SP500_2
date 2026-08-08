"""
Persistenz der Portfolio-Daten (data/portfolio.json) — lokal oder via GitHub.

Zwei Modi:
  - Lokal (Entwicklung): direkte Dateioperationen auf data/portfolio.json.
    Committen/pushen macht der Nutzer selbst wie gewohnt.
  - Streamlit Cloud: die Datei kann zur Laufzeit nicht per git geschrieben
    werden. Stattdessen liest/schreibt dieses Modul sie über die GitHub
    Contents-API und committet direkt auf 'main'. Beim nächsten Laden sieht
    die App den aktuellen Repo-Stand.

Konfiguration (nur Cloud-Modus nötig), aus st.secrets oder Umgebung:
    GITHUB_TOKEN   — fine-grained PAT mit contents:write auf das Repo
    GITHUB_REPO    — "owner/repo" (Default: tobiaskrayer/SP500_2)
    GITHUB_BRANCH  — Ziel-Branch (Default: main)
"""

import base64
import json
import os

import requests

PORTFOLIO_PATH = "data/portfolio.json"
_API = "https://api.github.com"
_DEFAULT_REPO = "tobiaskrayer/SP500_2"
_DEFAULT_BRANCH = "main"

# Lokaler Dateipfad (Repo-Root/data/portfolio.json)
_LOCAL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")

_EMPTY = {"positions": [], "realized": []}


def _secret(name: str, default: str = "") -> str:
    """Liest einen Wert aus st.secrets (falls verfügbar), sonst aus der Umgebung."""
    try:
        import streamlit as st
        try:
            return str(st.secrets[name])
        except (KeyError, FileNotFoundError):
            pass
    except Exception:
        pass
    return os.environ.get(name, default)


def is_cloud() -> bool:
    """True, wenn die App auf Streamlit Community Cloud läuft (siehe app.py)."""
    return bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_STREAMLIT_CLOUD"))


# ── Lokaler Modus ─────────────────────────────────────────────────────────────

def _load_local() -> tuple[dict, None]:
    if not os.path.exists(_LOCAL_PATH):
        return {"positions": [], "realized": []}, None
    with open(_LOCAL_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("positions", [])
    data.setdefault("realized", [])
    return data, None


def _save_local(data: dict, sha, message: str) -> None:
    os.makedirs(os.path.dirname(_LOCAL_PATH), exist_ok=True)
    tmp = _LOCAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _LOCAL_PATH)


# ── GitHub-Modus ──────────────────────────────────────────────────────────────

def _gh_config() -> tuple[str, str, str]:
    token = _secret("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN fehlt. Für das Speichern des Portfolios auf Streamlit "
            "Cloud wird ein fine-grained Personal Access Token mit contents:write "
            "benötigt (in den Streamlit-Secrets hinterlegen)."
        )
    repo = _secret("GITHUB_REPO", _DEFAULT_REPO)
    branch = _secret("GITHUB_BRANCH", _DEFAULT_BRANCH)
    return token, repo, branch


def _gh_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _load_github() -> tuple[dict, str | None]:
    token, repo, branch = _gh_config()
    res = requests.get(
        f"{_API}/repos/{repo}/contents/{PORTFOLIO_PATH}",
        headers=_gh_headers(token),
        params={"ref": branch},
        timeout=15,
    )
    if res.status_code == 404:
        # Datei existiert noch nicht — leeres Portfolio, kein SHA
        return {"positions": [], "realized": []}, None
    res.raise_for_status()
    payload = res.json()
    content = base64.b64decode(payload["content"]).decode("utf-8")
    data = json.loads(content) if content.strip() else dict(_EMPTY)
    data.setdefault("positions", [])
    data.setdefault("realized", [])
    return data, payload["sha"]


def _save_github(data: dict, sha: str | None, message: str) -> None:
    token, repo, branch = _gh_config()
    content_b64 = base64.b64encode(
        json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("ascii")
    body = {"message": message, "content": content_b64, "branch": branch}
    if sha:
        body["sha"] = sha
    res = requests.put(
        f"{_API}/repos/{repo}/contents/{PORTFOLIO_PATH}",
        headers=_gh_headers(token),
        json=body,
        timeout=20,
    )
    if res.status_code == 409:
        raise ConflictError(
            "Die Portfolio-Datei wurde zwischenzeitlich extern geändert. "
            "Lade die Seite neu und wiederhole die Aktion."
        )
    if res.status_code not in (200, 201):
        raise RuntimeError(f"GitHub-Commit fehlgeschlagen ({res.status_code}): {res.text}")


class ConflictError(RuntimeError):
    """SHA-Konflikt beim Schreiben: die Datei wurde zwischenzeitlich geändert."""


# ── Öffentliche API ───────────────────────────────────────────────────────────

def load() -> tuple[dict, str | None]:
    """
    Lädt das Portfolio. Gibt (data, sha) zurück; sha ist nur im Cloud-Modus
    relevant (für konfliktfreies Zurückschreiben), lokal immer None.
    """
    if is_cloud():
        return _load_github()
    return _load_local()


def save(data: dict, sha: str | None, message: str) -> None:
    """Speichert das Portfolio (lokal als Datei, in der Cloud als GitHub-Commit)."""
    if is_cloud():
        _save_github(data, sha, message)
    else:
        _save_local(data, sha, message)
