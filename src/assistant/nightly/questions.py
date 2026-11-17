"""Fragen-Beantworter: „Frage:“-Notizen in der Inbox bekommen über Nacht eine Antwort.

Die Antwort wird unter ``## Antwort des Assistenten`` an die Frage-Notiz angehängt,
mit den Quellen als Wikilinks. Die Notiz bleibt in der Inbox, damit sie morgens auffällt.
Steht schon eine Antwort darin, passiert nichts.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from assistant.ingest.parser import Note, split_frontmatter
from assistant.llm.answer import answer_from_hits
from assistant.llm.client import LLM
from assistant.nightly.inbox import MAX_ZEICHEN_IM_PROMPT, wikilink
from assistant.retrieval.search import Retriever

ANTWORT_UEBERSCHRIFT = "## Antwort des Assistenten"


def schon_beantwortet(text: str) -> bool:
    return ANTWORT_UEBERSCHRIFT in text


def frage_aus_notiz(note: Note, text: str) -> str:
    """Die Frage ist der Titel ohne „Frage:“ plus der Text der Notiz."""
    _, body = split_frontmatter(text)
    titel = note.title.removeprefix("Frage:").removeprefix("frage:").strip()
    zeilen = [z for z in body.splitlines() if not z.startswith("# ")]
    rest = "\n".join(zeilen).strip()
    return f"{titel}\n\n{rest}".strip()[:MAX_ZEICHEN_IM_PROMPT]


def beantworte(
    note: Note,
    text: str,
    retriever: Retriever,
    llm: LLM,
    namen: Counter[str],
    heute: date,
    *,
    inbox_dir: str = "00 Inbox",
    k: int = 5,
) -> tuple[str, int] | None:
    """Neuer Notiztext mit Antwort und Anzahl Quellen, ``None`` wenn schon beantwortet."""
    if schon_beantwortet(text):
        return None
    frage = frage_aus_notiz(note, text)
    # Die Frage-Notiz selbst (und andere Inbox-Notizen) sind keine Quelle.
    treffer = [
        h for h in retriever.search(frage, k * 2) if not h.chunk.path.startswith(f"{inbox_dir}/")
    ]
    antwort = answer_from_hits(frage, treffer[:k], llm)

    stempel = f"*{heute:%d.%m.%Y}, {llm.model_name}*"
    teile = [text.rstrip("\n"), "", ANTWORT_UEBERSCHRIFT, "", stempel, "", antwort.text]
    if antwort.sources:
        teile += ["", "**Quellen**", ""]
        for nr, h in enumerate(antwort.sources, start=1):
            link = wikilink(h.chunk.path, namen)
            ort = f" – {h.chunk.heading}" if h.chunk.heading else ""
            teile.append(f"{nr}. {link}{ort}")
    return "\n".join(teile) + "\n", len(antwort.sources)
