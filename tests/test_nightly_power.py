"""Gaming-PC nach getaner Arbeit ausschalten: Messen, Bewerten, Warten, SSH."""

import os
import shutil
import stat
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from assistant.config import Settings
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.llm.client import FakeLLM, ollama_busy
from assistant.nightly.job import Components, Optionen, run_nightly
from assistant.nightly.power import (
    GPU_BEFEHL,
    SHUTDOWN_BEFEHL,
    SPERRE_BEFEHL,
    FakePC,
    Messung,
    PCFehler,
    Regeln,
    SshPC,
    ausschalten_wenn_ruhig,
    bewerten,
    gpu_prozent,
    ist_gesperrt,
)
from assistant.nightly.wol import FakeWaker
from tests.conftest import DEMO_VAULT

GESPERRT = """
LogonUI.exe                  12345 Console                    1     51.200 K
"""
ENTSPERRT = "INFORMATION: Es werden keine Aufgaben mit den angegebenen Kriterien ausgeführt.\n"


def test_sperre_erkennen() -> None:
    assert ist_gesperrt(GESPERRT)
    assert not ist_gesperrt(ENTSPERRT)
    assert not ist_gesperrt("INFO: No tasks are running which match the specified criteria.")


def test_gpu() -> None:
    assert gpu_prozent("3\n") == 3
    assert gpu_prozent("12\n87\n") == 87
    assert gpu_prozent("nvidia-smi nicht gefunden") is None


JETZT = datetime(2026, 11, 18, 3, 0)
R = Regeln(ruhe_min=15, gpu_max=30, intervall_s=60)


def test_bewerten() -> None:
    assert bewerten(Messung(ollama_aktiv=False, gesperrt=True, gpu=2), R)[0] == "ruhig"
    lage, grund = bewerten(Messung(False, False, 2), R)
    assert lage == "abbrechen" and "entsperrt" in grund
    assert bewerten(Messung(True, True, 90), R)[0] == "warten"
    lage, grund = bewerten(Messung(False, True, 80), R)
    assert lage == "abbrechen" and "Spiel" in grund
    assert bewerten(Messung(False, True, None), R)[0] == "abbrechen"  # im Zweifel an lassen


class Uhr:
    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class SimPC(FakePC):
    """Ein gesperrter PC; ab ``entsperrt_bei`` Sekunden sitzt jemand davor."""

    def __init__(self, uhr: Uhr, entsperrt_bei: float | None = None, gpu: int = 1) -> None:
        super().__init__()
        self.uhr = uhr
        self.entsperrt_bei = entsperrt_bei
        self.gpu = gpu

    def run(self, befehl: str) -> str:
        self.befehle.append(befehl)
        if befehl == SPERRE_BEFEHL:
            if self.entsperrt_bei is not None and self.uhr.t >= self.entsperrt_bei:
                return ENTSPERRT
            return GESPERRT
        if befehl == GPU_BEFEHL:
            return f"{self.gpu}\n"
        return ""


def test_schaltet_nach_ruhe_aus() -> None:
    uhr = Uhr()
    pc = SimPC(uhr)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: False, R, sleep=uhr.sleep, clock=uhr.clock)
    assert ergebnis.startswith("Ausgeschaltet")
    assert pc.befehle[-1] == SHUTDOWN_BEFEHL
    assert uhr.t == 15 * 60


def test_wartet_solange_ollama_arbeitet() -> None:
    uhr = Uhr()
    pc = SimPC(uhr)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: uhr.t < 600, R, sleep=uhr.sleep, clock=uhr.clock)
    assert ergebnis.startswith("Ausgeschaltet")
    assert uhr.t == 600 + 15 * 60  # Ruhe zählt erst ab Ende der Arbeit


def test_bricht_ab_wenn_jemand_kommt() -> None:
    uhr = Uhr()
    pc = SimPC(uhr, entsperrt_bei=8 * 60)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: False, R, sleep=uhr.sleep, clock=uhr.clock)
    assert "entsperrt" in ergebnis
    assert SHUTDOWN_BEFEHL not in pc.befehle


def test_bricht_ab_wenn_gespielt_wird() -> None:
    uhr = Uhr()
    pc = SimPC(uhr, gpu=95)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: False, R, sleep=uhr.sleep, clock=uhr.clock)
    assert "Spiel" in ergebnis and SHUTDOWN_BEFEHL not in pc.befehle


def test_gibt_nach_max_warten_auf() -> None:
    uhr = Uhr()
    pc = SimPC(uhr)
    regeln = Regeln(ruhe_min=15, max_warten_min=30, intervall_s=60)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: True, regeln, sleep=uhr.sleep, clock=uhr.clock)
    assert "nie lange genug Ruhe" in ergebnis


def test_ssh_fehler_wird_gemeldet() -> None:
    class Weg(FakePC):
        def run(self, befehl: str) -> str:
            raise PCFehler("Verbindung abgelehnt")

    assert "Verbindung abgelehnt" in ausschalten_wenn_ruhig(Weg(), lambda: False, R)


def test_ollama_busy() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "qwen"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert ollama_busy("http://o", client=client)
    leer = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    assert not ollama_busy("http://o", client=leer)
    assert not ollama_busy("http://127.0.0.1:9", timeout_s=0.5)


def test_ssh_kopiert_schluessel_privat_und_loescht_ihn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    schluessel = tmp_path / "key"
    schluessel.write_text("geheim", encoding="utf-8")
    schluessel.chmod(0o777)  # wie unter Docker Desktop
    gesehen: list[tuple[list[str], int]] = []

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        kopie = Path(args[args.index("-i") + 1])
        gesehen.append((args, stat.S_IMODE(kopie.stat().st_mode)))
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pc = SshPC("demo@pc", schluessel, tmp_path / "state" / "known_hosts")
    assert pc.run(SPERRE_BEFEHL) == "ok"
    args, modus = gesehen[0]
    kopie = Path(args[args.index("-i") + 1])
    assert modus == 0o600 and kopie != schluessel
    assert not kopie.exists()  # Kopie ist wieder weg
    assert args[-2:] == ["demo@pc", SPERRE_BEFEHL]
    assert "BatchMode=yes" in args


@pytest.mark.parametrize(
    ("code", "stderr"), [(255, "Connection refused"), (1, "Zugriff verweigert")]
)
def test_ssh_fehler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, stderr: str
) -> None:
    schluessel = tmp_path / "key"
    schluessel.write_text("x", encoding="utf-8")

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, code, stdout="", stderr=stderr)

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PCFehler, match=stderr):
        SshPC("demo@pc", schluessel, tmp_path / "kh").run("shutdown /s")


def test_ssh_ohne_schluessel(tmp_path: Path) -> None:
    with pytest.raises(PCFehler):
        SshPC("demo@pc", tmp_path / "fehlt", tmp_path / "kh").run("x")


# --- Zusammenspiel mit dem Nachtlauf ----------------------------------------------


def _components(vault: Path, state: Path) -> Components:
    return Components(
        settings=Settings(vault_path=vault, nightly_state_path=state),
        embedder=FakeEmbedder(),
        store=InMemoryStore(),
        llm=FakeLLM(json_answer='{"ordner": "03 Wissen/Garten", "tags": [], "sicher": true}'),
    )


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    ziel = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, ziel)
    # Inbox-Notizen älter als der feste Testzeitpunkt, sonst gelten frisch ausgecheckte
    # Dateien als „aus der Zukunft“ und der Lauf hat nichts zu tun.
    vorher = (JETZT - timedelta(days=1)).timestamp()
    for datei in (ziel / "00 Inbox").glob("*.md"):
        os.utime(datei, (vorher, vorher))
    return ziel


@pytest.mark.parametrize(
    ("schon_wach", "probelauf", "erwartet"),
    [(False, False, ["aus"]), (True, False, []), (False, True, [])],
)
def test_nur_ausschalten_wenn_selbst_geweckt(
    vault: Path, tmp_path: Path, schon_wach: bool, probelauf: bool, erwartet: list[str]
) -> None:
    pruefungen = iter([schon_wach, True, True, True, True, True])
    aufrufe: list[str] = []

    def aus() -> str:
        aufrufe.append("aus")
        return "Ausgeschaltet nach 15 min Ruhe."

    lauf = run_nightly(
        _components(vault, tmp_path / "state"),
        vault,
        jetzt=JETZT,
        is_awake=lambda: next(pruefungen),
        waker=FakeWaker(),
        optionen=Optionen(min_alter=timedelta(0), min_score=0.0, git=False, probelauf=probelauf),
        ausschalten=aus,
        sleep=lambda _: None,
    )
    assert aufrufe == erwartet
    assert lauf.geweckt is not schon_wach
    if erwartet:
        assert lauf.hinweise[-1].startswith("Ausgeschaltet")
