"""Gaming-PC nach getaner Arbeit wieder ausschalten, aber nur wenn wirklich Ruhe ist.

Wake-on-LAN kann den PC nur einschalten. Zum Ausschalten meldet sich der Nachtjob per SSH
am Gaming-PC an (Windows hat einen OpenSSH-Server eingebaut) und ruft ``shutdown`` auf.
Das funktioniert gleich, ob der Nachtjob als Container auf dem Gaming-PC selbst läuft
(``host.docker.internal``) oder später auf dem Mini-PC (IP des Gaming-PCs).

Regeln, damit nie jemand beim Spielen oder Arbeiten gestört wird:

1. Nur wenn der Nachtjob den PC **selbst geweckt** hat. Lief er schon, bleibt er an.
2. Erst nach ``ruhe_min`` Minuten am Stück ohne Arbeit: Ollama hat kein Modell geladen
   (sonst läuft gerade eine Anfrage, z. B. aus dem Dashboard), die GPU ist ruhig.
3. Sobald jemand Maus oder Tastatur benutzt (der Windows-Leerlauf aus ``quser`` springt
   zurück) oder die GPU ohne Ollama arbeitet (Spiel), wird das Ausschalten
   **abgebrochen**: Dann sitzt jemand am PC.
4. ``shutdown /s /t 60``: eine Minute Vorwarnung, abbrechen mit ``shutdown /a``.
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


class PCFehler(RuntimeError):
    """Der Gaming-PC ist per SSH nicht erreichbar oder der Befehl schlug fehl."""


class RemotePC(Protocol):
    def run(self, befehl: str) -> str:
        """Führt ``befehl`` auf dem Gaming-PC aus und gibt die Ausgabe zurück."""
        ...


class SshPC:
    """Gaming-PC per SSH mit Schlüssel, ohne Passwort.

    Unter Docker Desktop hat ein eingebundener Schlüssel oft die Rechte 0777, dann verweigert
    ``ssh`` ihn. Deshalb wird er einmal in eine private Kopie mit 0600 geschrieben.
    """

    def __init__(self, ziel: str, schluessel: Path, known_hosts: Path) -> None:
        self.ziel = ziel  # z. B. "benutzer@host.docker.internal"
        self.schluessel = schluessel
        self.known_hosts = known_hosts
        self._kopie: Path | None = None

    def _schluessel(self) -> Path:
        if self._kopie is None:
            if not self.schluessel.is_file():
                raise PCFehler(f"SSH-Schlüssel nicht gefunden: {self.schluessel}")
            fd, pfad = tempfile.mkstemp(prefix="nachtjob-ssh-")
            os.close(fd)
            shutil.copyfile(self.schluessel, pfad)
            os.chmod(pfad, 0o600)
            self._kopie = Path(pfad)
        return self._kopie

    def run(self, befehl: str) -> str:
        self.known_hosts.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "ssh",
            "-i",
            str(self._schluessel()),
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
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PCFehler(f"SSH zu {self.ziel} fehlgeschlagen: {e}") from e
        if r.returncode == 255:  # Fehler von ssh selbst, nicht vom Befehl
            raise PCFehler(f"SSH zu {self.ziel} fehlgeschlagen: {r.stderr.strip()}")
        return r.stdout


class FakePC:
    """Für Tests: feste Antworten je Befehl, merkt sich alle Befehle."""

    def __init__(self, antworten: dict[str, str] | None = None) -> None:
        self.antworten = antworten or {}
        self.befehle: list[str] = []

    def run(self, befehl: str) -> str:
        self.befehle.append(befehl)
        for anfang, antwort in self.antworten.items():
            if befehl.startswith(anfang):
                return antwort
        return ""


_AKTIV = {"active", "aktiv"}


def parse_leerlauf(text: str) -> float | None:
    """``quser``-Leerlauf → Sekunden. ``none``/``.``/``Kein`` = 0, ``5`` = 5 min,
    ``1:05`` = 1 h 5 min, ``2+03:04`` = 2 Tage 3 h 4 min. Unbekannt → ``None``."""
    t = text.strip().lower()
    if t in {"none", ".", "kein", "keine"}:
        return 0.0
    m = re.fullmatch(r"(?:(\d+)\+)?(?:(\d+):)?(\d+)", t)
    if not m:
        return None
    tage, stunden, minuten = (int(x) if x else 0 for x in m.groups())
    return float(((tage * 24 + stunden) * 60 + minuten) * 60)


def benutzer_leerlauf_s(quser_ausgabe: str) -> float | None:
    """Kleinster Leerlauf aller aktiven Sitzungen, ``None`` wenn niemand angemeldet ist."""
    werte: list[float] = []
    for zeile in quser_ausgabe.splitlines()[1:]:
        teile = zeile.lstrip(">").split()
        for i, teil in enumerate(teile[:-1]):
            if teil.lower() in _AKTIV:
                wert = parse_leerlauf(teile[i + 1])
                if wert is not None:
                    werte.append(wert)
                break
    return min(werte) if werte else None


def gpu_prozent(nvidia_smi_ausgabe: str) -> float | None:
    """Höchste Auslastung aller GPUs aus ``nvidia-smi --query-gpu=utilization.gpu``."""
    werte = [float(z) for z in re.findall(r"^\s*(\d+(?:\.\d+)?)\s*$", nvidia_smi_ausgabe, re.M)]
    return max(werte) if werte else None


@dataclass(frozen=True)
class Messung:
    ollama_aktiv: bool  # Modell geladen = gerade (oder vor kurzem) eine Anfrage
    leerlauf_s: float | None  # seit wann niemand Maus/Tastatur benutzt hat
    gpu: float | None  # Prozent


def messen(pc: RemotePC, ollama_aktiv: Callable[[], bool]) -> Messung:
    quser = pc.run("quser")
    smi = pc.run("nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits")
    return Messung(ollama_aktiv(), benutzer_leerlauf_s(quser), gpu_prozent(smi))


@dataclass(frozen=True)
class Regeln:
    ruhe_min: float = 15.0  # so lange am Stück ruhig, dann aus
    benutzer_aktiv_min: float = 5.0  # Eingabe in den letzten 5 min = jemand sitzt davor
    gpu_max: float = 30.0  # mehr ohne Ollama = vermutlich ein Spiel
    max_warten_min: float = 120.0  # länger nie warten, dann bleibt der PC an
    intervall_s: float = 60.0


def bewerten(
    m: Messung, r: Regeln, vorher_leerlauf_s: float | None = None, beobachtet_s: float = 0.0
) -> tuple[str, str]:
    """(``"abbrechen"`` | ``"warten"`` | ``"ruhig"``, Grund).

    Benutzer aktiv heißt: Der Leerlauf ist seit der letzten Messung kleiner geworden (es gab
    eine Eingabe), oder er bleibt klein, obwohl schon länger beobachtet wird. Direkt nach dem
    Autologon ist der Leerlauf noch klein, ohne dass jemand da ist; das allein zählt nicht.
    """
    if m.leerlauf_s is not None:
        eingabe = vorher_leerlauf_s is not None and m.leerlauf_s + 30 < vorher_leerlauf_s
        grenze = r.benutzer_aktiv_min * 60
        bleibt_klein = m.leerlauf_s < grenze and beobachtet_s > grenze + r.intervall_s
        if eingabe or bleibt_klein:
            return "abbrechen", "Jemand benutzt den PC."
    if m.ollama_aktiv:
        return "warten", "Ollama arbeitet noch."
    if m.gpu is not None and m.gpu > r.gpu_max:
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
    vorher: float | None = None
    while clock() - start <= r.max_warten_min * 60:
        try:
            m = messen(pc, ollama_aktiv)
        except PCFehler as e:
            return f"Nicht ausgeschaltet: {e}"
        lage, grund = bewerten(m, r, vorher, clock() - start)
        vorher = m.leerlauf_s
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
