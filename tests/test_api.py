"""API-Tests mit Fakes: kein Ollama, keine Chroma, Vault ist eine Kopie des Demo-Vaults."""

import shutil
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from assistant.api import create_app
from assistant.components import Components
from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder, OllamaEmbedder
from assistant.index.store import InMemoryStore
from assistant.llm.client import FakeLLM, ollama_reachable
from tests.conftest import DEMO_VAULT


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ziel = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, ziel)
    return ziel


def _components(vault: Path) -> Components:
    return Components(
        settings=Settings(vault_path=vault, vault_name="demo_vault"),
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM("Ollama nutzt Port 11434 [1]."),
    )


@pytest.fixture
def client(vault: Path) -> TestClient:
    return TestClient(create_app(_components(vault), ping=lambda: True))


def test_status_vor_dem_ersten_index(client: TestClient) -> None:
    r = client.get("/status")
    assert r.status_code == 200
    daten = r.json()
    assert daten["chunks"] == 0
    assert daten["letzter_indexlauf"] is None
    assert daten["ollama_erreichbar"] is True
    assert daten["chat_modell"] == "fake-llm"


def test_leerer_index_meldet_409(client: TestClient) -> None:
    assert client.post("/search", json={"frage": "Port?"}).status_code == 409
    assert client.post("/ask", json={"frage": "Port?"}).status_code == 409


def test_reindex_ist_inkrementell_und_steht_im_status(client: TestClient) -> None:
    erst = client.post("/reindex").json()
    assert erst["notes"] == 25
    assert erst["embedded"] == erst["chunks"] > 0

    zweit = client.post("/reindex").json()
    assert zweit["embedded"] == 0

    status = client.get("/status").json()
    assert status["chunks"] == erst["chunks"]
    assert status["letzter_indexlauf"]["embedded"] == 0


def test_search_liefert_quellen_mit_obsidian_link(client: TestClient) -> None:
    client.post("/reindex")
    r = client.post("/search", json={"frage": "Wann sind die Eisheiligen?", "k": 3})
    assert r.status_code == 200
    quellen = r.json()["quellen"]
    assert 1 <= len(quellen) <= 3
    assert quellen[0]["titel"] == "Aussaatkalender"
    assert quellen[0]["link"].startswith("obsidian://open?vault=demo_vault&file=")
    assert [q["nr"] for q in quellen] == list(range(1, len(quellen) + 1))
    assert len({q["pfad"] for q in quellen}) == len(quellen)  # jede Notiz nur einmal


def test_ask_beantwortet_mit_quellen(client: TestClient) -> None:
    client.post("/reindex")
    r = client.post("/ask", json={"frage": "Welchen Port nutzt Ollama?"})
    assert r.status_code == 200
    daten = r.json()
    assert daten["antwort"] == "Ollama nutzt Port 11434 [1]."
    assert daten["modell"] == "fake-llm"
    assert any(q["pfad"].endswith("Ollama.md") for q in daten["quellen"])
    assert all(len(q["auszug"]) <= 300 for q in daten["quellen"])


@pytest.mark.parametrize("body", [{"frage": ""}, {"frage": "x", "k": 0}, {"k": 3}])
def test_ungueltige_anfragen(client: TestClient, body: dict[str, object]) -> None:
    assert client.post("/ask", json=body).status_code == 422


def test_ollama_schlaeft_ergibt_503(vault: Path) -> None:
    def kaputt(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused", request=request)

    c = _components(vault)
    c.embedder = OllamaEmbedder(
        "http://192.168.1.50:11434",
        "bge-m3",
        client=httpx.Client(transport=httpx.MockTransport(kaputt)),
    )
    client = TestClient(create_app(c, ping=lambda: False))
    r = client.post("/reindex")
    assert r.status_code == 503
    assert "Gaming-PC wach" in r.json()["detail"]
    assert client.get("/status").json()["ollama_erreichbar"] is False


def test_vault_fehlt_ergibt_500(tmp_path: Path) -> None:
    client = TestClient(create_app(_components(tmp_path / "gibtsnicht"), ping=lambda: True))
    r = client.post("/reindex")
    assert r.status_code == 500
    assert "Vault nicht gefunden" in r.json()["detail"]


def test_ollama_reachable() -> None:
    ok = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    assert ollama_reachable("http://x:11434", client=ok)

    def kaputt(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("weg", request=request)

    weg = httpx.Client(transport=httpx.MockTransport(kaputt))
    assert not ollama_reachable("http://x:11434", client=weg)
