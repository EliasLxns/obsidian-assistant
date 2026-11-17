"""Markdown-Parser für Obsidian-Notizen.

Liest Frontmatter, Tags, Wikilinks und die Gliederung nach Überschriften.
Codeblöcke werden dabei erkannt, damit ``# Kommentar`` in einem Shell-Beispiel
weder als Überschrift noch als Tag zählt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import yaml

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
# Tag: am Zeilenanfang oder nach Leerraum, mit mindestens einem Nicht-Ziffer-Zeichen.
_TAG = re.compile(r"(?<!\S)#([\w/-]*[^\W\d][\w/-]*)")
_WIKILINK = re.compile(r"!?\[\[([^\]|#^]*)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]")


@dataclass(frozen=True)
class Section:
    """Ein Abschnitt unter einer Überschrift.

    ``heading`` ist der Überschriftenpfad, z. B. ``"Docker Compose > Aufbau der Datei"``.
    Text vor der ersten Überschrift hat einen leeren Pfad.
    """

    heading: str
    level: int
    text: str


@dataclass(frozen=True)
class Note:
    path: str  # relativ zum Vault, mit "/" getrennt, z. B. "03 Wissen/Docker/Compose.md"
    title: str
    frontmatter: dict[str, Any] = field(default_factory=dict[str, Any])
    tags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()
    sections: tuple[Section, ...] = ()

    @property
    def name(self) -> str:
        """Notizname ohne Ordner und Endung, so wie Wikilinks ihn verwenden."""
        return Path(self.path).stem


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Trennt YAML-Frontmatter vom Inhalt. Ungültiges YAML ergibt ein leeres Dict."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    ende = text.find("\n---", 3)
    if ende == -1:
        return {}, text
    roh = text[4:ende]
    rest = text[ende + 4 :]
    rest = rest.removeprefix("\n")
    try:
        daten = yaml.safe_load(roh)
    except yaml.YAMLError:
        return {}, rest
    if not isinstance(daten, dict):
        return {}, rest
    return cast(dict[str, Any], daten), rest


def _frontmatter_tags(frontmatter: dict[str, Any]) -> list[str]:
    roh: object = frontmatter.get("tags", frontmatter.get("tag"))
    if roh is None:
        return []
    if isinstance(roh, str):
        teile = re.split(r"[,\s]+", roh)
    elif isinstance(roh, list):
        teile = [str(t) for t in cast(list[object], roh)]
    else:
        teile = [str(roh)]
    return [t.strip().lstrip("#") for t in teile if t.strip().lstrip("#")]


def _unique(werte: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(werte))


def parse_markdown(text: str, path: str) -> Note:
    """Zerlegt den Text einer Notiz. ``path`` ist der Pfad relativ zum Vault."""
    frontmatter, body = split_frontmatter(text)
    tags = _frontmatter_tags(frontmatter)
    links: list[str] = []

    sections: list[Section] = []
    stapel: list[tuple[int, str]] = []  # offene Überschriften (Ebene, Text)
    aktuell: list[str] = []
    ebene = 0
    in_code = False
    title: str | None = None

    def abschliessen() -> None:
        inhalt = "\n".join(aktuell).strip()
        pfad = " > ".join(h for _, h in stapel)
        if inhalt or pfad:
            sections.append(Section(heading=pfad, level=ebene, text=inhalt))

    for zeile in body.split("\n"):
        if _FENCE.match(zeile):
            in_code = not in_code
            aktuell.append(zeile)
            continue
        treffer = None if in_code else _HEADING.match(zeile)
        if treffer:
            abschliessen()
            aktuell = []
            ebene = len(treffer.group(1))
            ueberschrift = treffer.group(2).strip()
            if ebene == 1 and title is None:
                title = ueberschrift
            while stapel and stapel[-1][0] >= ebene:
                stapel.pop()
            stapel.append((ebene, ueberschrift))
            continue
        aktuell.append(zeile)
        if not in_code:
            ohne_code = _INLINE_CODE.sub("", zeile)
            tags.extend(_TAG.findall(ohne_code))
            links.extend(z.strip() for z in _WIKILINK.findall(ohne_code) if z.strip())
    abschliessen()

    # Leere Überschriften ohne Text (z. B. ein H1 direkt vor dem ersten H2) fallen weg.
    sections = [s for s in sections if s.text]
    return Note(
        path=path,
        title=title or Path(path).stem,
        frontmatter=frontmatter,
        tags=_unique(tags),
        links=_unique(links),
        sections=tuple(sections),
    )


def parse_file(file: Path, vault: Path) -> Note:
    rel = file.relative_to(vault).as_posix()
    return parse_markdown(file.read_text(encoding="utf-8"), rel)


def is_note(path: Path, vault: Path) -> bool:
    """Gehört die Datei in den Index? Markdown im Vault, nicht in versteckten Ordnern.

    Prüft nur den Pfad, nicht ob die Datei existiert (der Watcher meldet auch Gelöschtes).
    """
    try:
        teile = path.relative_to(vault).parts
    except ValueError:
        return False
    return path.suffix == ".md" and not any(t.startswith(".") for t in teile)


def iter_notes(vault: Path) -> list[Path]:
    """Alle Markdown-Dateien im Vault, ohne versteckte Ordner wie ``.obsidian`` oder ``.trash``."""
    return sorted(p for p in vault.rglob("*.md") if p.is_file() and is_note(p, vault))
