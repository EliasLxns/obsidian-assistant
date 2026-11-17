"""Suche über den Index.

Phase 1: reine Vektorsuche. Hybrid mit BM25 und Link-Erweiterung folgen in Phase 2
hinter derselben ``Retriever``-Schnittstelle.
"""

from __future__ import annotations

from assistant.index.embedder import Embedder
from assistant.index.store import Hit, VectorStore


def best_per_note(hits: list[Hit]) -> list[Hit]:
    """Behält pro Notiz nur den besten Chunk, Reihenfolge bleibt erhalten."""
    gesehen: set[str] = set()
    ergebnis: list[Hit] = []
    for hit in hits:
        if hit.chunk.path not in gesehen:
            gesehen.add(hit.chunk.path)
            ergebnis.append(hit)
    return ergebnis


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, *, oversample: int = 4) -> None:
        self.embedder = embedder
        self.store = store
        self.oversample = oversample

    def search(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` ähnlichsten Chunks."""
        return self.store.query(self.embedder.embed_query(query), k)

    def search_notes(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` besten Notizen, je mit ihrem besten Chunk.

        Es werden mehr Chunks geholt als nötig, weil eine Notiz mehrere Treffer haben kann.
        """
        hits = self.store.query(self.embedder.embed_query(query), k * self.oversample)
        return best_per_note(hits)[:k]
