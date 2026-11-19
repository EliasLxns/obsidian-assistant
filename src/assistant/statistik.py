"""Vault-Statistik fürs Dashboard: Notizen, Ordner, Tags, Links, zuletzt geändert.

Liest den Vault direkt (nur lesend), nicht den Index: So stimmt die Statistik auch, wenn
Ollama schläft und noch nicht alles eingebettet ist.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from assistant.ingest.parser import iter_notes, parse_markdown, split_frontmatter

_WORT = re.compile(r"\w+")


@dataclass(frozen=True)
class NotizKurz:
    pfad: str  # relativ zum Vault
    titel: str
    geaendert: datetime


@dataclass(frozen=True)
class ToterLink:
    notiz: str  # Pfad der Notiz mit dem Link
    ziel: str  # so wie im Wikilink geschrieben


@dataclass
class VaultStatistik:
    notizen: int = 0
    woerter: int = 0
    links: int = 0
    ordner: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    tags: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    tote_links: list[ToterLink] = field(default_factory=list[ToterLink])  # höchstens max_liste
    tote_links_anzahl: int = 0
    ohne_links: list[str] = field(default_factory=list[str])  # weder ein- noch ausgehend
    ohne_links_anzahl: int = 0
    zuletzt: list[NotizKurz] = field(default_factory=list[NotizKurz])


def _oberordner(rel: PurePosixPath) -> str:
    """``03 Wissen/Docker/Compose.md`` → ``03 Wissen/Docker``, Notizen im Wurzelordner → ``/``."""
    teile = rel.parent.parts[:2]
    return "/".join(teile) if teile else "/"


ANHANG = "\0anhang"  # Ziel eines Links auf eine Datei, die keine Notiz ist


class _Aufloeser:
    """Löst Wikilinks auf wie Obsidian: über den Pfad oder nur den Namen, ohne Groß/klein.

    Ein Punkt im Namen (``[[Version 1.2]]``) macht noch keinen Anhang: Erst wird eine Notiz
    gesucht, dann eine andere Datei (``![[Bild.png]]``).
    """

    def __init__(self, notizen: list[str], dateien: set[str]) -> None:
        self.pfade = {n.removesuffix(".md").casefold(): n for n in notizen}
        self.namen: dict[str, str] = {}
        for n in sorted(notizen, key=len):  # bei gleichen Namen gewinnt der kürzeste Pfad
            self.namen.setdefault(PurePosixPath(n).stem.casefold(), n)
        self.dateien = {d.casefold() for d in dateien}

    def ziel(self, link: str) -> str | None:
        """Pfad der Notiz, ``ANHANG`` oder ``None`` (toter Link)."""
        ohne = link.strip().removesuffix(".md").casefold()
        if ohne in self.pfade:
            return self.pfade[ohne]
        name = PurePosixPath(ohne).name
        if name in self.namen:
            return self.namen[name]
        return ANHANG if name in self.dateien else None


def _dateinamen(vault: Path) -> set[str]:
    """Namen aller Dateien außerhalb versteckter Ordner (``.git``, ``.obsidian``, ``.trash``)."""
    namen: set[str] = set()
    for p in vault.rglob("*"):
        teile = p.relative_to(vault).parts
        if not any(t.startswith(".") for t in teile) and p.is_file():
            namen.add(p.name)
    return namen


def vault_statistik(
    vault: Path, *, top_tags: int = 15, max_liste: int = 20, zuletzt: int = 8
) -> VaultStatistik:
    """Liest alle Notizen einmal. Für einige tausend Notizen dauert das unter einer Sekunde."""
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {vault}")
    dateien = iter_notes(vault)
    rels = [d.relative_to(vault).as_posix() for d in dateien]
    aufloeser = _Aufloeser(rels, _dateinamen(vault))

    s = VaultStatistik()
    ordner: Counter[str] = Counter()
    tags: Counter[str] = Counter()
    eingehend: Counter[str] = Counter()  # Notizpfad → Anzahl Links darauf
    ausgehend: dict[str, int] = {}
    kurz: list[NotizKurz] = []

    for datei, rel in zip(dateien, rels, strict=True):
        try:  # Sync oder Nachtjob können eine Datei gerade verschieben
            text = datei.read_text(encoding="utf-8", errors="replace")
            geaendert = datetime.fromtimestamp(datei.stat().st_mtime).astimezone()
        except OSError:
            continue
        note = parse_markdown(text, rel)
        _, body = split_frontmatter(text)
        s.notizen += 1
        s.woerter += len(_WORT.findall(body))
        ordner[_oberordner(PurePosixPath(rel))] += 1
        tags.update(t.lower() for t in note.tags)
        ausgehend[rel] = len(note.links)
        s.links += len(note.links)
        for link in note.links:
            ziel = aufloeser.ziel(link)
            if ziel is None:
                s.tote_links.append(ToterLink(rel, link))
            else:
                eingehend[ziel] += 1
        kurz.append(NotizKurz(rel, note.title, geaendert))

    s.ordner = sorted(ordner.items())
    s.tags = tags.most_common(top_tags)
    ohne = [pfad for pfad, n in ausgehend.items() if n == 0 and eingehend[pfad] == 0]
    s.ohne_links, s.ohne_links_anzahl = ohne[:max_liste], len(ohne)
    s.tote_links_anzahl = len(s.tote_links)
    s.tote_links = s.tote_links[:max_liste]
    s.zuletzt = sorted(kurz, key=lambda n: n.geaendert, reverse=True)[:zuletzt]
    return s
