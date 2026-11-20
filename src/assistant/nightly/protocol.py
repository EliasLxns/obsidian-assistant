"""Protokoll und Rückgängig für Nachtläufe.

Jeder Lauf wird zweimal festgehalten:

- als Markdown-Notiz in ``00 Inbox/Protokoll``, lesbar in Obsidian
- als JSON im Zustandsordner (außerhalb des Vaults) mit dem Originaltext jeder Notiz

Rückgängig stellt jede Notiz am alten Ort wieder her, Byte für Byte, auch die Zeilenenden.
Wurde eine Notiz seit dem Lauf von Hand geändert, bleibt sie, wie sie ist: Eigene Änderungen
gehen nie verloren.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

LAEUFE = "laeufe"


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Aktion:
    art: str  # einsortiert | pruefen | beantwortet | fehler
    quelle: str  # Pfad relativ zum Vault vor dem Lauf
    ziel: str = ""  # Pfad nach dem Lauf (bei „beantwortet“ gleich der Quelle)
    details: str = ""  # Tags, Links, Grund
    original: str = ""  # Text vor dem Lauf, für Rückgängig
    neu_hash: str = ""  # Hash des geschriebenen Textes


@dataclass
class Lauf:
    id: str  # z. B. 2026-11-18_0300
    start: str
    ende: str = ""
    probelauf: bool = False
    pc: str = ""  # „war wach“, „geweckt nach 42 s“, …
    ollama_benutzt: bool = False  # nur dann werden die Modelle danach entladen
    geweckt: bool = False  # nur dann darf der Nachtjob den PC danach ausschalten
    git_vorher: str | None = None
    git_nachher: str | None = None
    rueckgaengig: str = ""  # Zeitpunkt, zu dem der Lauf zurückgenommen wurde
    hinweise: list[str] = field(default_factory=list[str])
    aktionen: list[Aktion] = field(default_factory=list[Aktion])


def speichern(state: Path, lauf: Lauf) -> Path:
    ordner = state / LAEUFE
    ordner.mkdir(parents=True, exist_ok=True)
    datei = ordner / f"{lauf.id}.json"
    datei.write_text(json.dumps(asdict(lauf), ensure_ascii=False, indent=2), encoding="utf-8")
    return datei


def laden(datei: Path) -> Lauf:
    daten = cast(dict[str, Any], json.loads(datei.read_text(encoding="utf-8")))
    aktionen = [Aktion(**a) for a in cast(list[dict[str, Any]], daten.pop("aktionen", []))]
    return Lauf(**daten, aktionen=aktionen)


def alle_laeufe(state: Path) -> list[Path]:
    """JSON-Dateien aller Läufe, ältester zuerst (die ID ist sortierbar)."""
    ordner = state / LAEUFE
    return sorted(ordner.glob("*.json")) if ordner.is_dir() else []


_ART_TEXT = {
    "einsortiert": "Einsortiert",
    "pruefen": "Zum Prüfen",
    "beantwortet": "Beantwortet",
    "fehler": "Fehler",
}


def als_markdown(lauf: Lauf) -> str:
    def link(pfad: str) -> str:
        return f"[[{pfad.removesuffix('.md')}]]"

    kopf = "Probelauf (nichts geändert)" if lauf.probelauf else "Nachtlauf"
    zeilen = [
        "---",
        "tags: [nachtjob]",
        "---",
        f"# {kopf} {lauf.id}",
        "",
        f"- Start: {lauf.start}, Ende: {lauf.ende}",
        f"- Gaming-PC: {lauf.pc or 'unbekannt'}",
        f"- Git vorher: {f'`{lauf.git_vorher[:10]}`' if lauf.git_vorher else 'keine Änderung'}",
        f"- Rückgängig: `assistant nightly rueckgaengig {lauf.id}`",
    ]
    zeilen += [f"- {h}" for h in lauf.hinweise]
    zeilen += ["", "| Was | Notiz | Wohin | Details |", "|---|---|---|---|"]
    for a in lauf.aktionen:
        wohin = link(a.ziel) if a.ziel and a.ziel != a.quelle else ""
        notiz = link(a.quelle) if a.art == "beantwortet" else Path(a.quelle).stem
        details = a.details.replace("|", "/").replace("\n", " ")
        zeilen.append(f"| {_ART_TEXT.get(a.art, a.art)} | {notiz} | {wohin} | {details} |")
    if not lauf.aktionen:
        zeilen.append("| – | Inbox war leer | | |")
    return "\n".join(zeilen) + "\n"


def lesen(datei: Path) -> str:
    """Text ohne Umwandlung der Zeilenenden (``read_text`` macht unter Windows aus CRLF ``\n``)."""
    return datei.read_bytes().decode("utf-8")


def schreiben(datei: Path, text: str) -> None:
    """Erst in eine Hilfsdatei, dann umbenennen: Nie eine halb geschriebene Notiz.

    ``newline=""``: Die Zeilenenden landen so in der Datei, wie sie im Text stehen. Sonst würde
    Windows aus LF CRLF machen, und jede Notiz erschiene in Git als komplett geändert.
    """
    datei.parent.mkdir(parents=True, exist_ok=True)
    tmp = datei.with_name(f".{datei.name}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="")
    tmp.replace(datei)


def wie_original(neu: str, original: str) -> str:
    """Übernimmt die Zeilenenden des Originals: CRLF nur, wenn das Original durchgehend CRLF
    hat. Bei gemischten Zeilenenden bleibt der Text, wie er ist."""
    crlf = original.count("\r\n")
    if crlf and crlf == original.count("\n"):
        return neu.replace("\r\n", "\n").replace("\n", "\r\n")
    if not crlf:
        return neu.replace("\r\n", "\n")
    return neu


def rueckgaengig(vault: Path, lauf: Lauf, protokoll: Path | None = None) -> list[str]:
    """Stellt die Notizen eines Laufs wieder her. Gibt eine Zeile je Notiz zurück.

    ``protokoll``: die Protokoll-Notiz des Laufs. Sie wird gelöscht, wenn alles zurückgenommen
    ist; sonst bekommt sie einen Vermerk, was übersprungen wurde. Wurde gar nichts
    wiederhergestellt (z. B. ein Lauf mit nur Fehlern), bleibt sie unverändert.
    """
    meldungen: list[str] = []
    for a in reversed(lauf.aktionen):
        if a.art == "fehler" or not a.ziel:
            continue
        ziel, quelle = vault / a.ziel, vault / a.quelle
        if not ziel.is_file():
            meldungen.append(f"Übersprungen: {a.ziel} gibt es nicht mehr.")
            continue
        if text_hash(lesen(ziel)) != a.neu_hash:
            meldungen.append(f"Übersprungen: {a.ziel} wurde seitdem geändert.")
            continue
        if ziel != quelle and quelle.exists():
            meldungen.append(f"Übersprungen: {a.quelle} existiert schon wieder.")
            continue
        schreiben(quelle, a.original)
        if ziel != quelle:
            ziel.unlink()
        meldungen.append(f"Wiederhergestellt: {a.quelle}")
    wiederhergestellt = any(m.startswith("Wiederhergestellt") for m in meldungen)
    if protokoll is not None and protokoll.is_file() and wiederhergestellt:
        uebersprungen = [m for m in meldungen if m.startswith("Übersprungen")]
        if uebersprungen:
            vermerk = "\n## Rückgängig\n\n" + "".join(f"- {m}\n" for m in meldungen)
            schreiben(protokoll, lesen(protokoll) + vermerk)
        else:
            protokoll.unlink()
            meldungen.append(f"Protokoll entfernt: {protokoll.name}")
    return meldungen
