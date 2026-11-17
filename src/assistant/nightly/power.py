"""Gaming-PC nach getaner Arbeit wieder ausschalten, aber nur wenn wirklich Ruhe ist.

Wake-on-LAN kann den PC nur einschalten. Zum Ausschalten meldet sich der Nachtjob per SSH
am Gaming-PC an (Windows hat einen OpenSSH-Server eingebaut) und ruft ``shutdown`` auf.
Das funktioniert vom Mini-PC aus (IP des Gaming-PCs) genauso wie aus einem Container auf dem
Gaming-PC selbst (``host.docker.internal``).

Regeln, damit nie jemand beim Spielen oder Arbeiten gestört wird:

1. Nur wenn der Nachtjob den PC **selbst geweckt** hat. Lief er schon, bleibt er an.
2. Der PC muss **gesperrt** sein. Nach dem Autologon sperrt ihn eine geplante Aufgabe sofort;
   ist er entsperrt, sitzt jemand davor. Erkannt am Prozess ``LogonUI.exe``, den Windows
   nur für Sperr- und Anmeldebildschirm startet.
3. Erst nach ``ruhe_min`` Minuten am Stück ohne Arbeit: Ollama hat kein Modell geladen
   (sonst läuft gerade eine Anfrage, z. B. aus dem Dashboard), die GPU ist ruhig.
4. Entsperrt, GPU-Last ohne Ollama (Spiel) oder etwas nicht messbar → **abbrechen**,
   der PC bleibt an. Im Zweifel nie ausschalten.
5. ``shutdown /s /t 60``: eine Minute Vorwarnung, abbrechen mit ``shutdown /a``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SHUTDOWN_BEFEHL = 'shutdown /s /t 60 /c "Obsidian-Assistent: Arbeit erledigt, PC geht aus"'
SPERRE_BEFEHL = 'tasklist /FI "IMAGENAME eq LogonUI.exe" /NH'
GPU_BEFEHL = "nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits"


class PCFehler(RuntimeError):
    """Der Gaming-PC ist per SSH nicht erreichbar oder ein Befehl schlug fehl."""


class RemotePC(Protocol):
    def run(self, befehl: str) -> str:
        """Führt ``befehl`` auf dem Gaming-PC aus. Fehler (auch Exit-Code ≠ 0) → ``PCFehler``."""
        ...


class SshPC:
    """Gaming-PC per SSH mit Schlüssel, ohne Passwort.

    Unter Docker Desktop hat ein eingebundener Schlüssel oft die Rechte 0777, dann verweigert
    ``ssh`` ihn. Deshalb wird er für jeden Befehl in eine private Kopie (0600) geschrieben,
    die danach sofort wieder gelöscht wird.
    """

    def __init__(self, ziel: str, schluessel: Path, known_hosts: Path) -> None:
        self.ziel = ziel  # z. B. "benutzer@<IP-des-Gaming-PCs>"
        self.schluessel = schluessel
        self.known_hosts = known_hosts

    def run(self, befehl: str) -> str:
        try:
            self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="nachtjob-ssh-") as tmp:
                kopie = Path(tmp) / "key"
                shutil.copyfile(self.schluessel, kopie)
                os.chmod(kopie, 0o600)
                r = subprocess.run(
                    self._args(kopie, befehl),
                    capture_output=True,
                    text=True,
                    timeout=60,
                    check=False,
                )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PCFehler(f"SSH zu {self.ziel} fehlgeschlagen: {e}") from e
        if r.returncode != 0:
            fehler = (r.stderr or r.stdout).strip() or f"Exit-Code {r.returncode}"
            raise PCFehler(f"`{befehl.split()[0]}` auf {self.ziel} fehlgeschlagen: {fehler}")
        return r.stdout

    def _args(self, schluessel: Path, befehl: str) -> list[str]:
        return [
            "ssh",
            "-i",
            str(schluessel),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            f"UserKnownHostsFile={self.known_hosts}",
            self.ziel,
            befehl,
        ]


class FakePC:
    """Für Tests: feste Antworten je Befehlsanfang, merkt sich alle Befehle."""

    def __init__(self, antworten: dict[str, str] | None = None) -> None:
        self.antworten = antworten or {}
        self.befehle: list[str] = []

    def run(self, befehl: str) -> str:
        self.befehle.append(befehl)
        for anfang, antwort in self.antworten.items():
            if befehl.startswith(anfang):
                return antwort
        return ""


def ist_gesperrt(tasklist_ausgabe: str) -> bool:
    """Läuft ``LogonUI.exe``? Dann zeigt Windows Sperr- oder Anmeldebildschirm."""
    return "logonui.exe" in tasklist_ausgabe.lower()


def gpu_prozent(nvidia_smi_ausgabe: str) -> float | None:
    """Höchste Auslastung aller GPUs aus ``nvidia-smi --query-gpu=utilization.gpu``."""
    werte = [float(z) for z in re.findall(r"^\s*(\d+(?:\.\d+)?)\s*$", nvidia_smi_ausgabe, re.M)]
    return max(werte) if werte else None


@dataclass(frozen=True)
class Messung:
    ollama_aktiv: bool  # Modell geladen = gerade (oder vor kurzem) eine Anfrage
    gesperrt: bool  # Sperrbildschirm: niemand sitzt davor
    gpu: float | None  # Prozent, None = nicht messbar


def messen(pc: RemotePC, ollama_aktiv: Callable[[], bool]) -> Messung:
    gesperrt = ist_gesperrt(pc.run(SPERRE_BEFEHL))
    return Messung(ollama_aktiv(), gesperrt, gpu_prozent(pc.run(GPU_BEFEHL)))


@dataclass(frozen=True)
class Regeln:
    ruhe_min: float = 15.0  # so lange am Stück ruhig, dann aus
    gpu_max: float = 30.0  # mehr ohne Ollama = vermutlich ein Spiel
    max_warten_min: float = 120.0  # länger nie warten, dann bleibt der PC an
    intervall_s: float = 60.0


def bewerten(m: Messung, r: Regeln) -> tuple[str, str]:
    """(``"abbrechen"`` | ``"warten"`` | ``"ruhig"``, Grund)."""
    if not m.gesperrt:
        return "abbrechen", "Der PC ist entsperrt, jemand benutzt ihn."
    if m.ollama_aktiv:
        return "warten", "Ollama arbeitet noch."
    if m.gpu is None:
        return "abbrechen", "GPU-Last nicht messbar, sicherheitshalber bleibt der PC an."
    if m.gpu > r.gpu_max:
        return "abbrechen", f"GPU bei {m.gpu:.0f} % ohne Ollama, vermutlich ein Spiel."
    return "ruhig", "Alles ruhig."


def ausschalten_wenn_ruhig(
    pc: RemotePC,
    ollama_aktiv: Callable[[], bool],
    regeln: Regeln | None = None,
    *,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Wartet auf ``ruhe_min`` Minuten Ruhe und fährt den PC dann herunter.

    Gibt einen Satz fürs Protokoll zurück. Bricht ab, sobald jemand den PC benutzt.
    """
    r = regeln or Regeln()
    start = clock()
    ruhig_seit: float | None = None
    while clock() - start <= r.max_warten_min * 60:
        try:
            m = messen(pc, ollama_aktiv)
        except PCFehler as e:
            return f"Nicht ausgeschaltet: {e}"
        lage, grund = bewerten(m, r)
        if lage == "abbrechen":
            return f"Nicht ausgeschaltet: {grund}"
        if lage == "warten":
            ruhig_seit = None
        else:
            ruhig_seit = clock() if ruhig_seit is None else ruhig_seit
            if clock() - ruhig_seit >= r.ruhe_min * 60:
                try:
                    pc.run(SHUTDOWN_BEFEHL)
                except PCFehler as e:
                    return f"Nicht ausgeschaltet: {e}"
                return f"Ausgeschaltet nach {r.ruhe_min:.0f} min Ruhe."
        sleep(r.intervall_s)
    return f"Nicht ausgeschaltet: in {r.max_warten_min:.0f} min nie lange genug Ruhe."
