"""Zerlegt Notizen in Chunks: ein Chunk pro Abschnitt, lange Abschnitte mit Überlappung.

Warum nach Überschriften? Ein Abschnitt behandelt meist genau ein Thema. So passt
der Vektor eines Chunks gut zu einer Frage, und die Quelle lässt sich als
Überschrift anzeigen. Abschnitte über ``max_chars`` werden an Absatzgrenzen
geteilt; die Überlappung sorgt dafür, dass ein Gedanke an der Schnittstelle
in beiden Teilen vorkommt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from assistant.ingest.parser import Note

DEFAULT_MAX_CHARS = 1500
DEFAULT_OVERLAP = 200


@dataclass(frozen=True)
class Chunk:
    id: str  # "<pfad>#<nr>", stabil solange sich die Gliederung nicht ändert
    path: str
    title: str
    heading: str
    text: str
    tags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()

    @property
    def embed_text(self) -> str:
        """Text, der eingebettet wird: Titel und Überschrift geben dem Abschnitt Kontext."""
        kopf = self.title if not self.heading else f"{self.title} – {self.heading}"
        return f"{kopf}\n\n{self.text}"

    @property
    def hash(self) -> str:
        """Hash über den eingebetteten Text. Bleibt er gleich, muss nicht neu eingebettet werden."""
        return hashlib.sha256(self.embed_text.encode("utf-8")).hexdigest()


def _hart_teilen(text: str, max_chars: int) -> list[str]:
    """Teilt einen einzelnen zu langen Absatz an Leerzeichen."""
    teile: list[str] = []
    while len(text) > max_chars:
        schnitt = text.rfind(" ", 0, max_chars)
        if schnitt <= 0:
            schnitt = max_chars
        teile.append(text[:schnitt].strip())
        text = text[schnitt:].strip()
    if text:
        teile.append(text)
    return teile


def _ueberlappung(text: str, overlap: int) -> str:
    """Die letzten ``overlap`` Zeichen, an einer Wortgrenze begonnen."""
    if overlap <= 0 or len(text) <= overlap:
        return text if overlap > 0 else ""
    ende = text[-overlap:]
    leer = ende.find(" ")
    return ende[leer + 1 :] if 0 <= leer < len(ende) - 1 else ende


def split_text(
    text: str, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[str]:
    """Teilt Text an Absatzgrenzen in Stücke von höchstens etwa ``max_chars`` Zeichen.

    Jedes Stück ab dem zweiten beginnt mit dem Ende des vorherigen (``overlap`` Zeichen).
    """
    if max_chars <= 0:
        raise ValueError("max_chars muss positiv sein")
    if not 0 <= overlap < max_chars:
        raise ValueError("overlap muss zwischen 0 und max_chars liegen")
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []

    absaetze: list[str] = []
    for absatz in text.split("\n\n"):
        absatz = absatz.strip()
        if absatz:
            absaetze.extend(_hart_teilen(absatz, max_chars - overlap - 2))

    stuecke: list[str] = []
    aktuell = ""
    for absatz in absaetze:
        kandidat = f"{aktuell}\n\n{absatz}" if aktuell else absatz
        if len(kandidat) <= max_chars:
            aktuell = kandidat
            continue
        stuecke.append(aktuell)
        rest = _ueberlappung(aktuell, overlap)
        aktuell = f"{rest}\n\n{absatz}" if rest else absatz
    if aktuell:
        stuecke.append(aktuell)
    return stuecke


def chunk_note(
    note: Note, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in note.sections:
        for stueck in split_text(section.text, max_chars, overlap):
            chunks.append(
                Chunk(
                    id=f"{note.path}#{len(chunks)}",
                    path=note.path,
                    title=note.title,
                    heading=section.heading,
                    text=stueck,
                    tags=note.tags,
                    links=note.links,
                )
            )
    return chunks
