"""Vault-Statistik, Inbox-Übersicht und die neuen API-Endpunkte (Phase 4)."""

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from assistant.api import create_app
from assistant.components import Components
from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.llm.client import FakeLLM
from assistant.nightly.guard import pause_setzen
from assistant.nightly.job import Optionen, run_nightly
from assistant.nightly.uebersicht import inbox_uebersicht, naechster_lauf
from assistant.statistik import vault_statistik
from tests.conftest import DEMO_VAULT

JETZT = datetime(2026, 11, 18, 14, 0)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ziel = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, ziel)
    return ziel


def _settings(vault: Path, tmp_path: Path) -> Settings:
    return Settings(vault_path=vault, vault_name="demo_vault", nightly_state_path=tmp_path / "st")


# --- Vault-Statistik ------------------------------------------------------------------


def test_statistik_demo_vault() -> None:
    s = vault_statistik(DEMO_VAULT)
    assert s.notizen == 25
    assert s.woerter > 1000
    assert dict(s.ordner)["03 Wissen/Garten"] == 8
    assert s.tags[0][1] >= s.tags[-1][1]  # häufigste zuerst
    assert s.tote_links_anzahl == 0  # tests/test_demo_vault.py hält das sauber
    assert len(s.zuletzt) == 8


def test_tote_links_und_notizen_ohne_links(vault: Path) -> None:
    (vault / "Allein.md").write_text("# Allein\n\nKein Link.\n", encoding="utf-8")
    (vault / "Kaputt.md").write_text(
        "# Kaputt\n\n[[Gibt es nicht]] [[03 Wissen/Docker/Compose]] ![[Bild.png]]\n",
        encoding="utf-8",
    )
    s = vault_statistik(vault)
    assert {(t.notiz, t.ziel) for t in s.tote_links} == {
        ("Kaputt.md", "Gibt es nicht"),
        ("Kaputt.md", "Bild.png"),
    }
    assert s.tote_links_anzahl == 2
    assert "Allein.md" in s.ohne_links
    assert "Kaputt.md" not in s.ohne_links  # verlinkt selbst
    assert dict(s.ordner)["/"] == 2

    (vault / "Bild.png").write_bytes(b"png")  # Anhang da: Link nicht mehr tot
    assert vault_statistik(vault).tote_links_anzahl == 1


def test_links_wie_obsidian(vault: Path) -> None:
    """Punkt im Namen, Groß/klein egal, Anhänge in versteckten Ordnern zählen nicht."""
    (vault / "Version 1.2.md").write_text("# V\n", encoding="utf-8")
    (vault / "Links.md").write_text(
        "# Links\n\n[[Version 1.2]] [[compose]] ![[Weg.png]]\n", encoding="utf-8"
    )
    (vault / ".trash").mkdir()
    (vault / ".trash" / "Weg.png").write_bytes(b"png")
    s = vault_statistik(vault)
    assert [t.ziel for t in s.tote_links] == ["Weg.png"]
    assert "Version 1.2.md" not in s.ohne_links


def test_statistik_ohne_vault(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        vault_statistik(tmp_path / "fehlt")


# --- Inbox-Übersicht --------------------------------------------------------------------


def test_naechster_lauf() -> None:
    assert naechster_lauf(datetime(2026, 11, 18, 2, 0), "03:00") == datetime(2026, 11, 18, 3, 0)
    assert naechster_lauf(datetime(2026, 11, 18, 14, 0), "03:00") == datetime(2026, 11, 19, 3, 0)


def test_inbox_uebersicht_ohne_laeufe(vault: Path, tmp_path: Path) -> None:
    pruefen = vault / "00 Inbox" / "Prüfen"
    pruefen.mkdir()
    (pruefen / "Unklar.md").write_text("# Unklar\n", encoding="utf-8")
    u = inbox_uebersicht(_settings(vault, tmp_path), JETZT)
    arten = {n.pfad: n.art for n in u.offen}
    assert arten == {
        "00 Inbox/Frage Gel beim Halbmarathon.md": "frage",
        "00 Inbox/Idee Feuchtesensor.md": "notiz",
    }
    assert [n.titel for n in u.pruefen] == ["Unklar"]
    assert u.naechster_lauf == datetime(2026, 11, 19, 3, 0)
    assert u.pause is None and u.laeufe == []


def test_pause_verschiebt_naechsten_lauf(vault: Path, tmp_path: Path) -> None:
    s = _settings(vault, tmp_path)
    pause_setzen(s.nightly_state_path, JETZT + timedelta(hours=20), "LAN-Party")
    u = inbox_uebersicht(s, JETZT)
    assert u.pause is not None and u.pause.grund == "LAN-Party"
    assert u.naechster_lauf == datetime(2026, 11, 20, 3, 0)  # die Nacht zum 19. fällt aus

    pause_setzen(s.nightly_state_path, None)
    assert inbox_uebersicht(s, JETZT).naechster_lauf is None  # bis zum Aufheben


def _nachtlauf(vault: Path, s: Settings) -> None:
    gestern = (JETZT - timedelta(days=1)).timestamp()
    for datei in (vault / "00 Inbox").glob("*.md"):
        os.utime(datei, (gestern, gestern))
    c = Components(
        settings=s,
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM(
            "Antwort [1].", json_answer='{"ordner": "03 Wissen/Garten", "tags": [], "sicher": true}'
        ),
    )
    run_nightly(
        c,
        vault,
        jetzt=JETZT,
        is_awake=lambda: True,
        waker=None,
        optionen=Optionen(min_score=0.0, git=False),
    )


def test_inbox_uebersicht_nach_dem_lauf(vault: Path, tmp_path: Path) -> None:
    s = _settings(vault, tmp_path)
    _nachtlauf(vault, s)
    (s.nightly_state_path / "laeufe" / "kaputt.json").write_text("{", encoding="utf-8")
    (s.nightly_state_path / "laeufe" / "liste.json").write_text("[]", encoding="utf-8")
    u = inbox_uebersicht(s, JETZT)
    assert [n.art for n in u.offen] == ["beantwortet"]  # Idee ist einsortiert
    assert len(u.laeufe) == 1  # kaputte Datei wird übersprungen
    lauf = u.laeufe[0]
    assert lauf.zaehler == {"beantwortet": 1, "einsortiert": 1}
    assert {a.ziel for a in lauf.aktionen} >= {"03 Wissen/Garten/Idee Feuchtesensor.md"}


# --- API --------------------------------------------------------------------------------


@pytest.fixture
def client(vault: Path, tmp_path: Path) -> TestClient:
    s = _settings(vault, tmp_path)
    _nachtlauf(vault, s)
    c = Components(settings=s, embedder=FakeEmbedder(), store=InMemoryStore(), llm=FakeLLM("x"))
    return TestClient(create_app(c, ping=lambda: True, uhr=lambda: JETZT))


def test_api_inbox(client: TestClient) -> None:
    daten = client.get("/inbox").json()
    assert daten["naechster_lauf"] == "2026-11-19T03:00:00"
    assert daten["pause"] == {"aktiv": False, "bis": None, "grund": ""}
    assert daten["offen"][0]["link"].startswith("obsidian://open?vault=demo_vault&file=00%20Inbox")
    lauf = daten["laeufe"][0]
    assert "original" not in lauf["aktionen"][0]  # Originaltexte bleiben auf dem Server
    einsortiert = next(a for a in lauf["aktionen"] if a["art"] == "einsortiert")
    assert einsortiert["link"].endswith("file=03%20Wissen%2FGarten%2FIdee%20Feuchtesensor")


def test_api_vault(client: TestClient) -> None:
    daten = client.get("/vault").json()
    assert daten["notizen"] == 26  # 25 + Protokoll-Notiz des Laufs
    assert {"name": "03 Wissen/Garten", "anzahl": 9} in daten["ordner"]
    assert daten["zuletzt"][0]["link"].startswith("obsidian://")


def test_api_pause(client: TestClient) -> None:
    r = client.put("/nachtjob/pause", json={"stunden": 12, "grund": "Turnier"})
    assert r.json() == {"aktiv": True, "bis": "2026-11-19T02:00:00", "grund": "Turnier"}
    assert client.get("/nachtjob/pause").json()["aktiv"] is True
    assert client.get("/inbox").json()["naechster_lauf"] == "2026-11-19T03:00:00"

    assert client.put("/nachtjob/pause", json={}).json()["bis"] is None  # bis zum Aufheben
    assert client.get("/inbox").json()["naechster_lauf"] is None

    assert client.delete("/nachtjob/pause").json()["aktiv"] is False
    assert client.get("/nachtjob/pause").json()["aktiv"] is False


@pytest.mark.parametrize(
    "body", [{"stunden": 0}, {"stunden": 0.0001}, {"stunden": -1}, {"stunden": 1000}]
)
def test_api_pause_ungueltig(client: TestClient, body: dict[str, object]) -> None:
    assert client.put("/nachtjob/pause", json=body).status_code == 422


def test_api_ohne_vault(tmp_path: Path) -> None:
    c = Components(
        settings=_settings(tmp_path / "fehlt", tmp_path),
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM("x"),
    )
    client = TestClient(create_app(c, ping=lambda: True))
    assert client.get("/inbox").status_code == 500
    assert client.get("/vault").status_code == 500
