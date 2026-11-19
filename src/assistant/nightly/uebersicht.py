"""Was liegt in der Inbox, was hat der Nachtjob zuletzt getan? Für Dashboard und API.

Liest nur: die Inbox im Vault und die Läufe im Zustandsordner. Ändert nichts.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from assistant.config import Settings
from assistant.ingest.parser import parse_markdown
from assistant.nightly import protocol
from assistant.nightly.guard import Pause, aktive_pause, parse_uhrzeit, sekunden_bis
from assistant.nightly.inbox import PRUEFEN, ist_frage
from assistant.nightly.questions import schon_beantwortet


@dataclass(frozen=True)
class InboxNotiz:
    pfad: str  # relativ zum Vault
    titel: str
    art: str  # notiz | frage | beantwortet | pruefen
    geaendert: datetime


@dataclass(frozen=True)
class LaufAktion:
    art: str  # einsortiert | pruefen | beantwortet | fehler
    quelle: str
    ziel: str
    details: str


@dataclass(frozen=True)
class LaufKurz:
    id: str
    start: str
    ende: str
    probelauf: bool
    pc: str
    hinweise: list[str]
    zaehler: dict[str, int]  # art → Anzahl
    aktionen: list[LaufAktion]


@dataclass
class InboxUebersicht:
    offen: list[InboxNotiz] = field(default_factory=list[InboxNotiz])
    pruefen: list[InboxNotiz] = field(default_factory=list[InboxNotiz])
    naechster_lauf: datetime | None = None  # None: pausiert bis zum Aufheben
    pause: Pause | None = None
    laeufe: list[LaufKurz] = field(default_factory=list[LaufKurz])


def _notiz(datei: Path, vault: Path, art: str | None = None) -> InboxNotiz | None:
    """``None``, wenn die Datei inzwischen weg ist (Sync oder Nachtjob verschiebt gerade)."""
    rel = datei.relative_to(vault).as_posix()
    try:
        text = datei.read_text(encoding="utf-8", errors="replace")
        geaendert = datetime.fromtimestamp(datei.stat().st_mtime).astimezone()
    except OSError:
        return None
    note = parse_markdown(text, rel)
    if art is None and schon_beantwortet(text):
        art = "beantwortet"
    elif art is None:
        art = "frage" if ist_frage(note) else "notiz"
    return InboxNotiz(rel, note.title, art, geaendert)


def _notizen(ordner: Path, vault: Path, art: str | None = None) -> list[InboxNotiz]:
    if not ordner.is_dir():
        return []
    dateien = sorted(p for p in ordner.glob("*.md") if not p.name.startswith("."))
    return [n for d in dateien if (n := _notiz(d, vault, art)) is not None]


def lauf_kurz(lauf: protocol.Lauf) -> LaufKurz:
    """Ein Lauf ohne die Originaltexte der Notizen (die braucht nur Rückgängig)."""
    return LaufKurz(
        id=lauf.id,
        start=lauf.start,
        ende=lauf.ende,
        probelauf=lauf.probelauf,
        pc=lauf.pc,
        hinweise=list(lauf.hinweise),
        zaehler=dict(Counter(a.art for a in lauf.aktionen)),
        aktionen=[LaufAktion(a.art, a.quelle, a.ziel, a.details) for a in lauf.aktionen],
    )


def naechster_lauf(jetzt: datetime, nightly_time: str) -> datetime:
    """Nächste Startzeit des Dienstes, z. B. heute oder morgen um 03:00."""
    sekunden = sekunden_bis(jetzt, parse_uhrzeit(nightly_time))
    return (jetzt + timedelta(seconds=sekunden)).replace(microsecond=0)


def inbox_uebersicht(s: Settings, jetzt: datetime, *, laeufe: int = 10) -> InboxUebersicht:
    """``jetzt`` ohne Zeitzone, in Ortszeit (wie im Nachtjob-Dienst)."""
    vault = s.vault_path
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {vault}")
    inbox = vault / s.inbox_dir
    pause = aktive_pause(s.nightly_state_path, jetzt)
    # Während einer Pause startet der Dienst erst zur ersten Startzeit nach ihrem Ende.
    if pause is None:
        naechster: datetime | None = naechster_lauf(jetzt, s.nightly_time)
    elif pause.bis is None:
        naechster = None
    else:
        naechster = naechster_lauf(max(jetzt, pause.bis), s.nightly_time)
    u = InboxUebersicht(
        offen=_notizen(inbox, vault),
        pruefen=_notizen(inbox / PRUEFEN, vault, "pruefen"),
        naechster_lauf=naechster,
        pause=pause,
    )
    for datei in reversed(protocol.alle_laeufe(s.nightly_state_path)[-laeufe:]):
        try:
            u.laeufe.append(lauf_kurz(protocol.laden(datei)))
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            continue  # kaputte Datei: im Dashboard weglassen statt alles abzubrechen
    return u
