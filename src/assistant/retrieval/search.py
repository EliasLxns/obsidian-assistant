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

import logging
import threading
import time
from collections.abc import Callable
from typing import Literal

from assistant.index.embedder import Embedder, OllamaError
from assistant.index.store import Hit, VectorStore
from assistant.retrieval import links
from assistant.retrieval.bm25 import Bm25
from assistant.retrieval.links import LinkGraph

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
    Wer eine feste Schwelle braucht (Nachtjob: Links ab Kosinus 0,5, siehe ``Optionen``),
    nutzt ``vektor``.

    ``erreichbar`` (z. B. ``ollama_reachable`` mit 2 s Timeout) prüft vor der Vektorsuche, ob
    Ollama antwortet. Ohne die Prüfung würde ``hybrid`` bei schlafendem PC erst nach dem vollen
    Ollama-Timeout auf BM25 zurückfallen. Das Ergebnis gilt ``pruef_intervall_s`` Sekunden.
    ``rueckfall=False`` (Eval) lässt ``hybrid`` scheitern, statt still nur BM25 zu messen.
    ``link_erweiterung`` nimmt in ``bm25`` und ``hybrid`` die Notizen dazu, auf die die besten
    Treffer verlinken (siehe ``links.py``). In ``vektor`` bleibt sie aus, damit ``score`` der
    Kosinus bleibt.
    """

    def __init__(
        self,
        embedder: Embedder,
        store: VectorStore,
        *,
        oversample: int = 4,
        modus: str = "vektor",
        erreichbar: Callable[[], bool] | None = None,
        rueckfall: bool = True,
        link_erweiterung: bool = False,
        pruef_intervall_s: float = 30.0,
        bm25_max_alter_s: float = 60.0,
        uhr: Callable[[], float] = time.monotonic,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.oversample = oversample
        self.modus = suchmodus(modus)
        self.rueckfall = rueckfall
        self.link_erweiterung = link_erweiterung
        self._erreichbar = erreichbar
        self._pruef_intervall_s = pruef_intervall_s
        self._bm25_max_alter_s = bm25_max_alter_s
        self._uhr = uhr
        self._sperre = threading.Lock()
        self._ping: tuple[float, bool] | None = None  # (Zeitpunkt, Ergebnis)
        # (gebaut um, Anzahl Chunks, BM25, Link-Graph)
        self._bm25: tuple[float, int, Bm25, LinkGraph] | None = None

    def _bm25_index(self) -> Bm25:
        return self._indizes()[0]

    def _indizes(self) -> tuple[Bm25, LinkGraph]:
        """BM25 über alle Chunks im Store.

        Neu gebaut, wenn sich die Anzahl der Chunks ändert oder der Index älter als
        ``bm25_max_alter_s`` ist. So kostet eine Suche nur ein ``count()``, und geänderte
        Notizen sind spätestens nach einer Minute auch per Stichwort auffindbar.
        """
        jetzt, anzahl = self._uhr(), self.store.count()
        with self._sperre:  # eine Instanz bedient mehrere API-Threads
            cache = self._bm25
            if cache and cache[1] == anzahl and jetzt - cache[0] < self._bm25_max_alter_s:
                return cache[2], cache[3]
            chunks = self.store.alle_chunks()
            index, graph = Bm25(chunks), LinkGraph(chunks)
            self._bm25 = (jetzt, anzahl, index, graph)
            return index, graph

    def _ollama_da(self) -> bool:
        if self._erreichbar is None:
            return True
        jetzt = self._uhr()
        with self._sperre:
            if self._ping and jetzt - self._ping[0] < self._pruef_intervall_s:
                return self._ping[1]
        da = self._erreichbar()
        with self._sperre:
            self._ping = (jetzt, da)
        return da

    def _treffer(self, query: str, n: int) -> tuple[list[Hit], Suchmodus]:
        """Treffer und der Modus, mit dem tatsächlich gesucht wurde."""
        if self.modus == "vektor":
            return self.store.query(self.embedder.embed_query(query), n), "vektor"
        bm25, graph = self._indizes()
        stichwort = bm25.search(query, n)
        vektor: list[Hit] | None = None
        if self.modus == "hybrid":
            if not self.rueckfall:
                vektor = self.store.query(self.embedder.embed_query(query), n)
            elif self._ollama_da():
                try:
                    vektor = self.store.query(self.embedder.embed_query(query), n)
                except OllamaError as e:
                    log.warning("Ollama nicht erreichbar, suche nur mit BM25: %s", e)
                    with self._sperre:
                        self._ping = (self._uhr(), False)
        listen = [stichwort] if vektor is None else [vektor, stichwort]
        modus: Suchmodus = "bm25" if vektor is None else "hybrid"
        if not self.link_erweiterung:
            return (stichwort if vektor is None else rrf(*listen)[:n]), modus
        basis = stichwort if vektor is None else rrf(*listen)
        return links.einfuegen(basis, graph.verlinkt(basis, stichwort))[:n], modus

    def search(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` besten Chunks."""
        return self.search_mit_modus(query, k)[0]

    def search_mit_modus(self, query: str, k: int = 5) -> tuple[list[Hit], Suchmodus]:
        """Wie ``search``, dazu der tatsächlich genutzte Modus (``bm25``, wenn ``hybrid``
        ohne Ollama weitersuchen musste)."""
        if self.modus == "vektor":
            return self._treffer(query, k)
        # Für die Fusion beide Listen etwas länger holen, sonst fehlen Kandidaten.
        hits, modus = self._treffer(query, k * self.oversample)
        return hits[:k], modus

    def search_notes(self, query: str, k: int = 5) -> list[Hit]:
        """Die ``k`` besten Notizen, je mit ihrem besten Chunk."""
        return self.search_notes_mit_modus(query, k)[0]

    def search_notes_mit_modus(self, query: str, k: int = 5) -> tuple[list[Hit], Suchmodus]:
        """Wie ``search_notes``, dazu der tatsächlich genutzte Modus.

        Es werden mehr Chunks geholt als nötig, weil eine Notiz mehrere Treffer haben kann.
        """
        hits, modus = self._treffer(query, k * self.oversample)
        return best_per_note(hits)[:k], modus
