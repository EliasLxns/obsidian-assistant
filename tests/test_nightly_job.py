"""Ein ganzer Nachtlauf auf einer Kopie des Demo-Vaults, mit Fakes statt Ollama."""

import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from assistant.cli import Components, main
from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.llm.client import FakeLLM
from assistant.nightly import protocol
from assistant.nightly.job import Optionen, run_nightly
from assistant.nightly.wol import FakeWaker
from tests.conftest import DEMO_VAULT

IDEE = "00 Inbox/Idee Feuchtesensor.md"
FRAGE = "00 Inbox/Frage Gel beim Halbmarathon.md"
SICHER = '{"ordner": "03 Wissen/Garten", "tags": ["garten", "sensor"], "sicher": true}'
UNSICHER = '{"ordner": "03 Wissen/Garten", "tags": ["garten"], "sicher": false, "grund": "Oder?"}'
JETZT = datetime(2026, 11, 18, 3, 0)


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ziel = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, ziel)
    # Inbox-Notizen „vom Vortag“ des festen Testzeitpunkts: frisch ausgecheckte Dateien wären
    # sonst zu neu (min_alter). Nicht datetime.now(), sonst schlägt der Test ab dem Tag nach
    # JETZT fehl.
    gestern = (JETZT - timedelta(days=1)).timestamp()
    for datei in (ziel / "00 Inbox").glob("*.md"):
        os.utime(datei, (gestern, gestern))
    return ziel


def _components(vault: Path, state: Path, json_answer: str = SICHER) -> Components:
    return Components(
        settings=Settings(vault_path=vault, vault_name="demo_vault", nightly_state_path=state),
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM("Nach etwa 45 Minuten, dann alle 30 Minuten [1].", json_answer=json_answer),
    )


def _lauf(c: Components, vault: Path, **kwargs: object) -> protocol.Lauf:
    optionen = Optionen(min_alter=timedelta(0), min_score=0.0, **kwargs)  # type: ignore[arg-type]
    return run_nightly(c, vault, jetzt=JETZT, is_awake=lambda: True, waker=None, optionen=optionen)


def _git_log(vault: Path) -> list[str]:
    aus = subprocess.run(
        ["git", "-c", "safe.directory=*", "log", "--format=%s"],
        cwd=vault,
        capture_output=True,
        text=True,
        check=True,
    )
    return aus.stdout.splitlines()


def test_nachtlauf_sortiert_beantwortet_und_protokolliert(vault: Path, tmp_path: Path) -> None:
    c = _components(vault, tmp_path / "state")
    lauf = _lauf(c, vault)

    arten = {a.quelle: a.art for a in lauf.aktionen}
    assert arten == {IDEE: "einsortiert", FRAGE: "beantwortet"}

    # Idee ist einsortiert, mit Tags und Links
    assert not (vault / IDEE).exists()
    neu = (vault / "03 Wissen/Garten/Idee Feuchtesensor.md").read_text(encoding="utf-8")
    assert "tags: [garten, sensor]" in neu
    assert "## Verwandt" in neu and "[[" in neu

    # Frage bleibt in der Inbox und hat eine Antwort mit Quellen außerhalb der Inbox
    frage = (vault / FRAGE).read_text(encoding="utf-8")
    assert "## Antwort des Assistenten" in frage
    assert "Nach etwa 45 Minuten" in frage
    assert "1. [[" in frage and "[[Idee Feuchtesensor" not in frage

    # Protokoll in Obsidian, JSON für Rückgängig, zwei Git-Commits
    md = vault / "00 Inbox/Protokoll" / f"Nachtjob {lauf.id}.md"
    assert "Einsortiert" in md.read_text(encoding="utf-8")
    assert len(protocol.alle_laeufe(tmp_path / "state")) == 1
    assert _git_log(vault) == [
        f"Nachtjob: Lauf {lauf.id}",
        f"Nachtjob: Stand vor Lauf {lauf.id}",
    ]


def test_zweiter_lauf_hat_nichts_zu_tun(vault: Path, tmp_path: Path) -> None:
    c = _components(vault, tmp_path / "state")
    _lauf(c, vault)
    zweiter = _lauf(c, vault)
    assert zweiter.aktionen == []


def test_unsicher_landet_in_pruefen(vault: Path, tmp_path: Path) -> None:
    c = _components(vault, tmp_path / "state", json_answer=UNSICHER)
    lauf = _lauf(c, vault)
    aktion = next(a for a in lauf.aktionen if a.quelle == IDEE)
    assert aktion.art == "pruefen"
    assert aktion.ziel == "00 Inbox/Prüfen/Idee Feuchtesensor.md"
    assert "Vorschlag 03 Wissen/Garten" in aktion.details
    assert (vault / aktion.ziel).is_file()


def test_vorhandene_notiz_wird_nicht_ueberschrieben(vault: Path, tmp_path: Path) -> None:
    belegt = vault / "03 Wissen/Garten/Idee Feuchtesensor.md"
    belegt.write_text("# Schon da\n", encoding="utf-8")
    lauf = _lauf(_components(vault, tmp_path / "state"), vault)
    aktion = next(a for a in lauf.aktionen if a.quelle == IDEE)
    assert aktion.art == "pruefen"
    assert belegt.read_text(encoding="utf-8") == "# Schon da\n"


def test_rueckgaengig(vault: Path, tmp_path: Path) -> None:
    vorher = {p: (vault / p).read_text(encoding="utf-8") for p in (IDEE, FRAGE)}
    lauf = _lauf(_components(vault, tmp_path / "state"), vault)

    meldungen = protocol.rueckgaengig(vault, lauf)
    assert sorted(meldungen) == [f"Wiederhergestellt: {FRAGE}", f"Wiederhergestellt: {IDEE}"]
    for pfad, text in vorher.items():
        assert (vault / pfad).read_text(encoding="utf-8") == text
    assert not (vault / "03 Wissen/Garten/Idee Feuchtesensor.md").exists()


def test_rueckgaengig_laesst_eigene_aenderungen_in_ruhe(vault: Path, tmp_path: Path) -> None:
    lauf = _lauf(_components(vault, tmp_path / "state"), vault)
    ziel = vault / "03 Wissen/Garten/Idee Feuchtesensor.md"
    ziel.write_text(ziel.read_text(encoding="utf-8") + "\nNoch ein Gedanke.\n", encoding="utf-8")

    meldungen = protocol.rueckgaengig(vault, lauf)
    assert any("wurde seitdem geändert" in m for m in meldungen)
    assert ziel.exists() and not (vault / IDEE).exists()


def test_probelauf_aendert_nichts(vault: Path, tmp_path: Path) -> None:
    vorher = sorted(p.relative_to(vault) for p in vault.rglob("*"))
    lauf = _lauf(_components(vault, tmp_path / "state"), vault, probelauf=True)
    assert lauf.probelauf and len(lauf.aktionen) == 2
    assert sorted(p.relative_to(vault) for p in vault.rglob("*")) == vorher


def test_ollama_nicht_erreichbar(vault: Path, tmp_path: Path) -> None:
    c = _components(vault, tmp_path / "state")
    waker = FakeWaker()
    entladen: list[bool] = []
    lauf = run_nightly(
        c,
        vault,
        jetzt=JETZT,
        is_awake=lambda: False,
        waker=waker,
        wol_timeout_s=10,
        sleep=lambda _: None,
        entladen=lambda: entladen.append(True),
    )
    assert waker.gesendet >= 1
    assert lauf.pc == "nicht erreichbar"
    assert any(h.startswith("Abgebrochen") for h in lauf.hinweise)
    assert (vault / IDEE).exists() and not (vault / ".git").exists()
    assert entladen == []  # Ollama nicht benutzt: PC in Ruhe lassen


def test_gaming_schutz_wenn_pc_schon_wach(vault: Path, tmp_path: Path) -> None:
    entladen: list[bool] = []
    lauf = run_nightly(
        _components(vault, tmp_path / "state"),
        vault,
        jetzt=JETZT,
        is_awake=lambda: True,
        waker=None,
        optionen=Optionen(min_alter=timedelta(0), schon_wach_ueberspringen=True),
        entladen=lambda: entladen.append(True),
    )
    assert lauf.aktionen == []
    assert "vielleicht wird gespielt" in lauf.hinweise[0]
    assert entladen == []  # auch die Modelle bleiben, wie sie sind


def test_leere_inbox_weckt_den_pc_nicht(vault: Path, tmp_path: Path) -> None:
    (vault / IDEE).unlink()
    (vault / FRAGE).write_text("# Frage: x\n\n## Antwort des Assistenten\n", encoding="utf-8")
    waker = FakeWaker()
    lauf = run_nightly(
        _components(vault, tmp_path / "state"),
        vault,
        jetzt=JETZT,
        is_awake=lambda: False,
        waker=waker,
        optionen=Optionen(min_alter=timedelta(0)),
    )
    assert waker.gesendet == 0
    assert lauf.pc == "nicht gebraucht"


def test_kaputte_notiz_stoppt_den_lauf_nicht(vault: Path, tmp_path: Path) -> None:
    kaputt = vault / "00 Inbox/Latin1.md"
    kaputt.write_bytes("# Grüße\n".encode("latin-1"))
    gestern = (JETZT - timedelta(days=1)).timestamp()
    os.utime(kaputt, (gestern, gestern))
    lauf = _lauf(_components(vault, tmp_path / "state"), vault)
    arten = {a.quelle: a.art for a in lauf.aktionen}
    assert arten["00 Inbox/Latin1.md"] == "fehler"
    assert arten[IDEE] == "einsortiert"
    assert (vault / "00 Inbox/Protokoll" / f"Nachtjob {lauf.id}.md").exists()


def test_rueckgaengig_ueberspringt_leere_laeufe(vault: Path, tmp_path: Path) -> None:
    state = tmp_path / "state"
    _lauf(_components(vault, state), vault)
    zweiter = run_nightly(  # nächste Nacht: nichts zu tun
        _components(vault, state),
        vault,
        jetzt=JETZT + timedelta(days=1),
        is_awake=lambda: True,
        waker=None,
        optionen=Optionen(min_alter=timedelta(0)),
    )
    assert zweiter.aktionen == []
    assert main(["nightly", "rueckgaengig"], FakeApp(vault, state)) == 0
    assert (vault / IDEE).exists()


class FakeApp:
    def __init__(self, vault: Path, state: Path) -> None:
        self.components = _components(vault, state)
        self.components.settings = Settings(
            vault_path=vault,
            nightly_state_path=state,
            nightly_window="01:00-06:00",
            ollama_url="http://127.0.0.1:9",  # dort antwortet niemand
        )

    def __call__(self, settings: Settings) -> Components:
        return self.components


def test_cli_pause_laeufe_rueckgaengig(
    vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state = tmp_path / "state"
    app = FakeApp(vault, state)

    assert main(["nightly", "pause", "--stunden", "2", "--grund", "LAN"], app) == 0
    assert main(["nightly", "--jetzt"], app) == 1  # PC nicht erreichbar, Abbruch
    assert "Abgebrochen" in capsys.readouterr().out
    assert main(["nightly", "weiter"], app) == 0

    _lauf(_components(vault, state), vault)
    assert main(["nightly", "laeufe"], app) == 0
    aus = capsys.readouterr().out
    assert "1 beantwortet, 1 einsortiert" in aus

    assert main(["nightly", "rueckgaengig"], app) == 0
    assert "Wiederhergestellt" in capsys.readouterr().out
    assert (vault / IDEE).exists()


def test_cli_ausserhalb_des_fensters(vault: Path, tmp_path: Path) -> None:
    app = FakeApp(vault, tmp_path / "state")
    jetzt = datetime.now()
    fenster = f"{(jetzt + timedelta(hours=2)):%H:%M}-{(jetzt + timedelta(hours=3)):%H:%M}"
    app.components.settings = Settings(
        vault_path=vault, nightly_state_path=tmp_path / "state", nightly_window=fenster
    )
    assert main(["nightly"], app) == 0
    assert protocol.alle_laeufe(tmp_path / "state") == []
