"""Suche über den Index: Vektor, BM25 oder beides (hybrid).

Die Modi:

- ``vektor``: Kosinus-Ähnlichkeit der Embeddings. Findet Umschreibungen.
- ``bm25``: Stichwortsuche (siehe ``bm25.py``). Findet exakte Begriffe und braucht kein Ollama.
- ``hybrid``: beide Ranglisten per Reciprocal Rank Fusion (RRF) zusammengeführt. Ist Ollama
  nicht erreichbar, sucht ``hybrid`` nur mit BM25 weiter, statt zu scheitern.

RRF nutzt nur die Plätze, nicht die Scores: ``score = Σ 1 / (60 + platz)``. So müssen
Kosinus-Werte (0 bis 1) und BM25-Werte (offen nach oben) nicht vergleichbar gemacht werden.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Literal

from assistant.index.embedder import Embedder, OllamaError
from assistant.index.store import Hit, VectorStore
from assistant.retrieval.bm25 import Bm25

log = logging.getLogger(__name__)

Suchmodus = Literal["vektor", "bm25", "hybrid"]
SUCHMODI: tuple[Suchmodus, ...] = ("vektor", "bm25", "hybrid")
RRF_K = 60  # Standardwert aus dem RRF-Paper (Cormack et al. 2009)


def suchmodus(wert: str) -> Suchmodus:
    """Prüft einen Modus aus ``.env`` oder der Kommandozeile."""
    for m in SUCHMODI:
        if wert == m:
            return m
    raise ValueError(f"Unbekannter Suchmodus '{wert}', erlaubt: {', '.join(SUCHMODI)}")


def best_per_note(hits: list[Hit]) -> list[Hit]:
    """Behält pro Notiz nur den besten Chunk, Reihenfolge bleibt erhalten."""
    gesehen: set[str] = set()
    ergebnis: list[Hit] = []
    for hit in hits:
        if hit.chunk.path not in gesehen:
            gesehen.add(hit.chunk.path)
            ergebnis.append(hit)
    return ergebnis


def rrf(*ranglisten: list[Hit], k: int = RRF_K) -> list[Hit]:
    """Führt Ranglisten zusammen. ``score`` ist danach der RRF-Wert, höher ist besser."""
    punkte: dict[str, float] = {}
    chunks: dict[str, Hit] = {}
    for liste in ranglisten:
        for platz, hit in enumerate(liste, start=1):
            punkte[hit.chunk.id] = punkte.get(hit.chunk.id, 0.0) + 1 / (k + platz)
            chunks.setdefault(hit.chunk.id, hit)
    reihenfolge = sorted(punkte, key=lambda i: punkte[i], reverse=True)
    return [Hit(chunks[i].chunk, round(punkte[i], 6)) for i in reihenfolge]


class Retriever:
    """``modus`` gilt für ``search`` und ``search_notes``.

    ``score`` hängt vom Modus ab: Kosinus (vektor), BM25-Wert (bm25) oder RRF-Wert (hybrid).
    Wer eine feste Schwelle braucht (Nachtjob: Links erst ab Kosinus 0,3), nutzt ``vektor``.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        oversample: int = 4,
        modus: Suchmodus = "vektor",
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.oversample = oversample
        self.modus = suchmodus(modus)
        self._bm25: Bm25 | None = None
        self._bm25_stand = ""

    def _bm25_index(self) -> Bm25:
        """BM25 über alle Chunks im Store, neu gebaut nur, wenn sich der Index geändert hat."""
        fp = self.store.fingerprints()
        stand = hashlib.sha256(
            "\n".join(f"{i}\t{f.hash}" for i, f in sorted(fp.items())).encode()
        ).hexdigest()
        if self._bm25 is None or stand != self._bm25_stand:
            self._bm25 = Bm25(self.store.alle_chunks())
            self._bm25_stand = stand
        return self._bm25

    def _treffer(self, query: str, n: int) -> tuple[list[Hit], Suchmodus]:
        """Treffer und der Modus, mit dem tatsächlich gesucht wurde."""
        if self.modus == "bm25":
            return self._bm25_index().search(query, n), "bm25"
        if self.modus == "vektor":
            return self.store.query(self.embedder.embed_query(query), n), "vektor"
        stichwort = self._bm25_index().search(query, n)
        try:
            vektor = self.store.query(self.embedder.embed_query(query), n)
        except OllamaError as e:
            log.warning("Ollama nicht erreichbar, suche nur mit BM25: %s", e)
            return stichwort, "bm25"
        return rrf(vektor, stichwort)[:n], "hybrid"

    def search(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` besten Chunks."""
        if self.modus == "vektor":
            return self._treffer(query, k)[0]
        # Für die Fusion beide Listen etwas länger holen, sonst fehlen Kandidaten.
        return self._treffer(query, k * self.oversample)[0][:k]

    def search_notes(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` besten Notizen, je mit ihrem besten Chunk."""
        return self.search_notes_mit_modus(query, k)[0]

    def search_notes_mit_modus(self, query: str, k: int = 5) -> tuple[list[Hit], Suchmodus]:
        """Wie ``search_notes``, dazu der tatsächlich genutzte Modus (``bm25``, wenn ``hybrid``
        ohne Ollama weitersuchen musste).

        Es werden mehr Chunks geholt als nötig, weil eine Notiz mehrere Treffer haben kann.
        """
        hits, modus = self._treffer(query, k * self.oversample)
        return best_per_note(hits)[:k], modus
