"""Dashboard: Hilfsfunktionen, API-Client und die Seiten gegen eine echte API mit Fakes."""

import os
import shutil
import socket
import threading
import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import httpx
import pytest
import streamlit as st
import uvicorn
from streamlit.testing.v1 import AppTest

from ansicht import md_escape, wikilink_chip, zaehler_text, zeitpunkt
from api_client import ApiClient, ApiFehler
from assistant.api import create_app
from assistant.components import Components
from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.ingest.indexer import index_vault
from assistant.llm.client import FakeLLM
from assistant.nightly.job import Optionen, run_nightly
from tests.conftest import DEMO_VAULT, ROOT

APP = str(ROOT / "dashboard" / "app.py")

# --- reine Hilfsfunktionen ------------------------------------------------------------


def test_zeitpunkt() -> None:
    heute = date(2026, 11, 18)
    assert zeitpunkt("2026-11-18T03:00:00", heute) == "heute 03:00"
    assert zeitpunkt("2026-11-17T14:20:00", heute) == "gestern 14:20"
    assert zeitpunkt("2026-11-19T03:00:00", heute) == "morgen 03:00"
    assert zeitpunkt("2026-11-02T09:05:00", heute) == "02.11. 09:05"
    assert zeitpunkt("2025-12-24T18:00:00", heute) == "24.12.2025 18:00"
    assert zeitpunkt(None) == "–"
    assert zeitpunkt("kaputt") == "kaputt"


def test_wikilink_chip_maskiert_markdown() -> None:
    link = "obsidian://open?vault=demo_vault&file=03%20Wissen%2FDocker%2FCompose"
    assert wikilink_chip("Compose", link) == rf"[\[\[Compose\]\]]({link})"
    assert md_escape("a_b *c* [d]") == r"a\_b \*c\* \[d\]"


def test_zaehler_text() -> None:
    assert zaehler_text({"einsortiert": 2, "pruefen": 1}) == "2 einsortiert, 1 zum Prüfen"
    assert zaehler_text({}) == "nichts zu tun"


# --- API-Client -----------------------------------------------------------------------


def _client(handler: httpx.MockTransport) -> ApiClient:
    return ApiClient("http://api:8080/", client=httpx.Client(transport=handler))


def test_client_meldet_fehler_der_api() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "http://api:8080/ask"
        return httpx.Response(503, json={"detail": "Ist der Gaming-PC wach?"})

    with pytest.raises(ApiFehler) as e:
        _client(httpx.MockTransport(handler)).fragen("Port?")
    assert e.value.status == 503 and "Gaming-PC" in e.value.meldung


def test_client_lesbare_pruefmeldung_und_falscher_dienst() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/ask":
            detail = [{"type": "string_too_long", "msg": "String should have at most 2000"}]
            return httpx.Response(422, json={"detail": detail})
        return httpx.Response(200, text="<html>kein JSON</html>")

    c = _client(httpx.MockTransport(handler))
    with pytest.raises(ApiFehler, match=r"^String should have at most 2000$"):
        c.fragen("x" * 3000)
    with pytest.raises(ApiFehler, match="antwortet nicht wie die API"):
        c.status()


def test_client_api_nicht_erreichbar() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=req)

    with pytest.raises(ApiFehler) as e:
        _client(httpx.MockTransport(handler)).status()
    assert e.value.status == 0 and "nicht erreichbar" in e.value.meldung


def test_client_url_aus_umgebung(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_URL", "http://beispiel:9000/")
    assert ApiClient().basis_url == "http://beispiel:9000"


# --- Seiten gegen eine laufende API ---------------------------------------------------


def _freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def api_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Echte API (uvicorn im Thread) mit Fakes, Demo-Vault und einem Nachtlauf."""
    tmp = tmp_path_factory.mktemp("dashboard")
    vault = tmp / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    gestern = (datetime.now() - timedelta(days=1)).timestamp()
    for datei in (vault / "00 Inbox").glob("*.md"):
        os.utime(datei, (gestern, gestern))
    s = Settings(vault_path=vault, vault_name="demo_vault", nightly_state_path=tmp / "state")
    c = Components(
        settings=s,
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM(
            "Ollama nutzt Port 11434 [1].",
            json_answer='{"ordner": "03 Wissen/Garten", "tags": ["garten"], "sicher": true}',
        ),
    )
    index_vault(vault, c.embedder, c.store)
    run_nightly(
        c,
        vault,
        jetzt=datetime.now(),
        is_awake=lambda: True,
        waker=None,
        optionen=Optionen(min_score=0.0, git=False),
    )
    port = _freier_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(c, ping=lambda: True), port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def app(api_url: str, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("API_URL", api_url)
    st.cache_data.clear()
    st.cache_resource.clear()
    return AppTest.from_file(APP, default_timeout=30)


def _badges(at: AppTest) -> list[str]:
    """``st.badge`` erscheint in AppTest als Markdown wie ``:green-badge[:material/x: Text]``."""
    return [str(m.value) for m in at.markdown if "-badge[" in str(m.value)]


def _texte(at: AppTest) -> str:
    teile = [m.value for m in at.markdown] + [c.value for c in at.caption]
    return "\n".join(str(t) for t in teile)


def test_fragen_mit_antwort_und_quellen(app: AppTest) -> None:
    app.run()
    assert not app.exception
    kopf = _badges(app)
    assert "Gaming-PC wach" in kopf[0] and "Index:" in kopf[1] and "Nachtjob" in kopf[2]
    app.text_input(key="frage").set_value("Welchen Port nutzt Ollama?")
    app.button[0].click().run()
    assert not app.exception
    texte = _texte(app)
    assert "Ollama nutzt Port 11434 [1]." in texte
    assert r"[\[\[Ollama\]\]](obsidian://open?vault=demo_vault&file=" in texte
    assert "Formuliert von fake-llm" in texte


def test_nur_suchen_zeigt_auszuege(app: AppTest) -> None:
    app.run()
    app.text_input(key="frage").set_value("Eisheilige")
    app.checkbox(key="nur_suchen").check()
    app.button[0].click().run()
    assert not app.exception
    texte = _texte(app)
    assert "Aussaatkalender" in texte
    assert "Formuliert von" not in texte


@pytest.mark.parametrize("seite", ["seiten/inbox.py", "seiten/vault.py", "seiten/system.py"])
def test_seiten_laufen(app: AppTest, seite: str) -> None:
    app.run()
    app.switch_page(seite).run()
    assert not app.exception
    assert app.title[0].value in {"Inbox", "Vault", "System"}


def test_inbox_pausieren_und_aufheben(app: AppTest) -> None:
    app.run()
    app.switch_page("seiten/inbox.py").run()
    app.button[0].click().run()  # „Pausieren“ im Formular
    assert not app.exception
    assert "Gaming-Schutz an" in _texte(app)
    app.button[0].click().run()  # „Pause aufheben“
    assert "Gaming-Schutz an" not in _texte(app)


def test_api_weg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_URL", f"http://127.0.0.1:{_freier_port()}")
    st.cache_data.clear()
    st.cache_resource.clear()
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert len(_badges(at)) == 1 and "API nicht erreichbar" in _badges(at)[0]
