"""Gaming-Schutz: Der Nachtjob soll nie stören, wenn am Gaming-PC jemand spielt.

Vom Server aus lässt sich nicht sehen, ob ein Spiel läuft. Deshalb mehrere einfache Regeln:

1. **Zeitfenster:** Der Nachtjob läuft nur nachts (Standard 01:00–06:00).
2. **Pause:** ``assistant nightly pause`` setzt einen Schalter, z. B. für eine lange Session.
   Er gilt bis zu einem Zeitpunkt oder bis ``assistant nightly weiter``.
3. **Schon wach:** Mit ``NIGHTLY_SKIP_IF_AWAKE=true`` lässt der Nachtjob einen PC in Ruhe,
   der schon lief, bevor er ihn geweckt hat. Sinnvoll, sobald der Stack auf dem Mini-PC läuft.
4. **GPU freigeben:** Nach jedem Lauf werden die Modelle sofort aus dem VRAM entladen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any, cast

PAUSE_DATEI = "pause.json"


def parse_uhrzeit(text: str) -> time:
    """``"03:00"`` → ``time(3, 0)``."""
    try:
        stunde, minute = text.strip().split(":")
        return time(int(stunde), int(minute))
    except ValueError as e:
        raise ValueError(f"Uhrzeit im Format HH:MM erwartet, nicht {text!r}") from e


def parse_fenster(text: str) -> tuple[time, time]:
    """``"01:00-06:00"`` → (Beginn, Ende). Ein Fenster darf über Mitternacht gehen."""
    teile = text.split("-")
    if len(teile) != 2:
        raise ValueError(f"Zeitfenster im Format HH:MM-HH:MM erwartet, nicht {text!r}")
    return parse_uhrzeit(teile[0]), parse_uhrzeit(teile[1])


def im_fenster(jetzt: datetime, fenster: tuple[time, time]) -> bool:
    beginn, ende = fenster
    t = jetzt.time()
    if beginn <= ende:
        return beginn <= t < ende
    return t >= beginn or t < ende  # z. B. 23:00-05:00


def sekunden_bis(jetzt: datetime, uhrzeit: time) -> float:
    """Sekunden bis zum nächsten Zeitpunkt ``uhrzeit`` (heute oder morgen)."""
    ziel = jetzt.replace(hour=uhrzeit.hour, minute=uhrzeit.minute, second=0, microsecond=0)
    if ziel <= jetzt:
        ziel += timedelta(days=1)
    return (ziel - jetzt).total_seconds()


@dataclass(frozen=True)
class Pause:
    bis: datetime | None  # None: bis ``weiter``
    grund: str = ""


def pause_setzen(state: Path, bis: datetime | None, grund: str = "") -> None:
    state.mkdir(parents=True, exist_ok=True)
    daten = {"bis": bis.isoformat() if bis else None, "grund": grund}
    (state / PAUSE_DATEI).write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")


def pause_aufheben(state: Path) -> bool:
    datei = state / PAUSE_DATEI
    if datei.exists():
        datei.unlink()
        return True
    return False


def aktive_pause(state: Path, jetzt: datetime) -> Pause | None:
    """Die Pause, wenn sie gerade gilt. Abgelaufene Pausen werden ignoriert."""
    datei = state / PAUSE_DATEI
    if not datei.is_file():
        return None
    try:
        daten = cast(dict[str, Any], json.loads(datei.read_text(encoding="utf-8")))
        bis = datetime.fromisoformat(daten["bis"]) if daten.get("bis") else None
    except (ValueError, KeyError, TypeError):
        return Pause(bis=None, grund="Pause-Datei unlesbar, sicherheitshalber pausiert")
    if bis is not None and jetzt >= bis:
        return None
    return Pause(bis=bis, grund=str(daten.get("grund") or ""))


def warum_nicht(state: Path, jetzt: datetime, fenster: tuple[time, time]) -> str | None:
    """Grund, warum der Nachtjob jetzt nicht laufen soll, sonst ``None``."""
    pause = aktive_pause(state, jetzt)
    if pause is not None:
        bis = f" bis {pause.bis:%d.%m. %H:%M}" if pause.bis else ""
        grund = f" ({pause.grund})" if pause.grund else ""
        return f"Pausiert{bis}{grund}."
    if not im_fenster(jetzt, fenster):
        return (
            f"Außerhalb des Zeitfensters {fenster[0]:%H:%M}–{fenster[1]:%H:%M}. "
            "Mit --jetzt trotzdem starten."
        )
    return None
