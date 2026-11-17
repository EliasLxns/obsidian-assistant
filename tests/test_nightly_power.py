"""Gaming-PC nach getaner Arbeit ausschalten: Messen, Bewerten, Warten, SSH."""

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
    SHUTDOWN_BEFEHL,
    FakePC,
    Messung,
    PCFehler,
    Regeln,
    SshPC,
    ausschalten_wenn_ruhig,
    benutzer_leerlauf_s,
    bewerten,
    gpu_prozent,
    parse_leerlauf,
)
from assistant.nightly.wol import FakeWaker
from tests.conftest import DEMO_VAULT

QUSER_EN = """ USERNAME              SESSIONNAME        ID  STATE   IDLE TIME  LOGON TIME
>demo                  console             1  Active      1:05  18.11.2026 03:00
 gast                                      2  Disc           5  17.11.2026 20:00
"""
QUSER_DE = """ BENUTZERNAME          SITZUNGSNAME       ID  STATUS  LEERLAUF   ANMELDEZEIT
>demo                  console             1  Aktiv          .  18.11.2026 03:00
"""


@pytest.mark.parametrize(
    ("text", "sekunden"),
    [("none", 0), (".", 0), ("Kein", 0), ("5", 300), ("1:05", 3900), ("2+03:04", 183840)],
)
def test_leerlauf_formate(text: str, sekunden: float) -> None:
    assert parse_leerlauf(text) == sekunden


def test_leerlauf_unbekannt() -> None:
    assert parse_leerlauf("gestern") is None


def test_quser_englisch_und_deutsch() -> None:
    assert benutzer_leerlauf_s(QUSER_EN) == 3900  # getrennte Sitzung zählt nicht
    assert benutzer_leerlauf_s(QUSER_DE) == 0
    assert benutzer_leerlauf_s("Kein Benutzer vorhanden für *\n") is None


def test_gpu() -> None:
    assert gpu_prozent("3\n") == 3
    assert gpu_prozent("12\n87\n") == 87
    assert gpu_prozent("nvidia-smi nicht gefunden") is None


R = Regeln(ruhe_min=15, benutzer_aktiv_min=5, gpu_max=30, intervall_s=60)


def test_bewerten() -> None:
    ruhig = Messung(ollama_aktiv=False, leerlauf_s=0, gpu=2)
    # Direkt nach dem Autologon ist der Leerlauf klein, ohne dass jemand da ist
    assert bewerten(ruhig, R)[0] == "ruhig"
    # Leerlauf springt zurück: Eingabe
    assert bewerten(ruhig, R, vorher_leerlauf_s=600, beobachtet_s=600)[0] == "abbrechen"
    # Bleibt klein, obwohl schon lange beobachtet: jemand tippt ständig
    assert bewerten(ruhig, R, vorher_leerlauf_s=0, beobachtet_s=420)[0] == "abbrechen"
    assert bewerten(Messung(True, 900, 90), R)[0] == "warten"
    lage, grund = bewerten(Messung(False, 900, 80), R)
    assert lage == "abbrechen" and "Spiel" in grund


class Uhr:
    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


class SimPC(FakePC):
    """Ein PC, an dem niemand sitzt: Der Leerlauf wächst mit der Zeit."""

    def __init__(self, uhr: Uhr, eingabe_bei: float | None = None, gpu: int = 1) -> None:
        super().__init__()
        self.uhr = uhr
        self.eingabe_bei = eingabe_bei
        self.gpu = gpu

    def run(self, befehl: str) -> str:
        self.befehle.append(befehl)
        if befehl == "quser":
            seit = self.uhr.t
            if self.eingabe_bei is not None and self.uhr.t >= self.eingabe_bei:
                seit = self.uhr.t - self.eingabe_bei
            minuten = int(seit // 60)
            return f"USERNAME SESSIONNAME ID STATE IDLE LOGON\n>demo console 1 Active {minuten} x\n"
        if befehl.startswith("nvidia-smi"):
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
    pc = SimPC(uhr, eingabe_bei=8 * 60)
    ergebnis = ausschalten_wenn_ruhig(pc, lambda: False, R, sleep=uhr.sleep, clock=uhr.clock)
    assert "Jemand benutzt den PC" in ergebnis
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


def test_ssh_kopiert_schluessel_privat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schluessel = tmp_path / "key"
    schluessel.write_text("geheim", encoding="utf-8")
    schluessel.chmod(0o777)  # wie unter Docker Desktop
    aufrufe: list[list[str]] = []

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        aufrufe.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    pc = SshPC("demo@pc", schluessel, tmp_path / "state" / "known_hosts")
    assert pc.run("quser") == "ok"
    args = aufrufe[0]
    kopie = Path(args[args.index("-i") + 1])
    assert kopie != schluessel
    assert stat.S_IMODE(kopie.stat().st_mode) == 0o600
    assert args[-2:] == ["demo@pc", "quser"]
    assert "BatchMode=yes" in args


def test_ssh_fehler_255(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    schluessel = tmp_path / "key"
    schluessel.write_text("x", encoding="utf-8")

    def fake_run(args: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 255, stdout="", stderr="Connection refused")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(PCFehler, match="Connection refused"):
        SshPC("demo@pc", schluessel, tmp_path / "kh").run("quser")


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
    return ziel


@pytest.mark.parametrize(("schon_wach", "erwartet"), [(False, ["aus"]), (True, [])])
def test_nur_ausschalten_wenn_selbst_geweckt(
    vault: Path, tmp_path: Path, schon_wach: bool, erwartet: list[str]
) -> None:
    pruefungen = iter([schon_wach, True, True, True, True, True])
    aufrufe: list[str] = []

    def aus() -> str:
        aufrufe.append("aus")
        return "Ausgeschaltet nach 15 min Ruhe."

    lauf = run_nightly(
        _components(vault, tmp_path / "state"),
        vault,
        jetzt=datetime(2026, 11, 18, 3, 0),
        is_awake=lambda: next(pruefungen),
        waker=FakeWaker(),
        optionen=Optionen(min_alter=timedelta(0), min_score=0.0, git=False),
        ausschalten=aus,
        sleep=lambda _: None,
    )
    assert aufrufe == erwartet
    assert lauf.geweckt is not schon_wach
    if erwartet:
        assert lauf.hinweise[-1].startswith("Ausgeschaltet")
