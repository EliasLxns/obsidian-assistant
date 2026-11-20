"""Link-Erweiterung: Notizen, auf die die besten Treffer verlinken, kommen mit in die Auswahl.

Wer in Obsidian schreibt, verlinkt Zusammenhänge selbst: Der Halbmarathon-Bericht verlinkt den
Trainingsplan, die Tomaten-Notiz die Mischkultur. Fragen, die mehrere Notizen brauchen, finden
so auch die zweite Notiz, wenn sie selbst andere Wörter benutzt als die Frage.

Die verlinkten Notizen kommen direkt hinter die besten ``QUELLEN`` Notizen: zuerst die, auf
die mehrere Treffer zeigen, dann nach ihrem Platz in der Stichwortsuche. Die ersten Plätze
bleiben so unverändert. Eine Fusion per RRF hat im Eval Treffer@1 verschlechtert, weil schon
kleine Zusatzpunkte die knappen Abstände der ersten Plätze umdrehen.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import PurePosixPath

from assistant.index.store import Hit
from assistant.ingest.chunker import Chunk

QUELLEN = 3  # aus wie vielen der besten Notizen die Links genommen werden


class LinkGraph:
    """Löst Wikilinks auf Notizpfade auf und kennt die Chunks jeder Notiz."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks: dict[str, list[Chunk]] = {}
        for c in chunks:
            self.chunks.setdefault(c.path, []).append(c)
        self._pfade = {p.removesuffix(".md").casefold(): p for p in self.chunks}
        self._namen: dict[str, str] = {}
        for p in sorted(self.chunks, key=len):  # gleiche Namen: der kürzeste Pfad gewinnt
            self._namen.setdefault(PurePosixPath(p).stem.casefold(), p)

    def ziel(self, link: str) -> str | None:
        """``Compose`` oder ``03 Wissen/Docker/Compose`` → Pfad der Notiz, sonst ``None``."""
        ohne = link.split("#")[0].strip().removesuffix(".md").casefold()
        return self._pfade.get(ohne) or self._namen.get(PurePosixPath(ohne).name)

    def verlinkt(self, treffer: Sequence[Hit], stichwort: Sequence[Hit]) -> list[Hit]:
        """Rangliste der Notizen, auf die die besten ``QUELLEN`` Notizen verlinken.

        Je Notiz ein Chunk: der beste aus der Stichwortsuche, sonst der erste der Notiz.
        Notizen, die schon unter den besten Treffern sind, fehlen hier.
        """
        oben: list[str] = []
        for h in treffer:
            if h.chunk.path not in oben:
                oben.append(h.chunk.path)
            if len(oben) == QUELLEN:
                break
        zaehler: Counter[str] = Counter()
        for pfad in oben:
            ziele = {self.ziel(link) for c in self.chunks.get(pfad, []) for link in c.links}
            zaehler.update(z for z in ziele if z and z not in oben)
        if not zaehler:
            return []

        bester: dict[str, tuple[int, Hit]] = {}
        for platz, h in enumerate(stichwort):
            bester.setdefault(h.chunk.path, (platz, h))
        unbekannt = len(stichwort)

        def rang(pfad: str) -> tuple[int, int]:
            return (-zaehler[pfad], bester.get(pfad, (unbekannt, None))[0])

        ergebnis: list[Hit] = []
        for pfad in sorted(zaehler, key=rang):
            hit = bester[pfad][1] if pfad in bester else Hit(self.chunks[pfad][0], 0.0)
            ergebnis.append(hit)
        return ergebnis


def einfuegen(treffer: list[Hit], verlinkt: list[Hit]) -> list[Hit]:
    """Setzt ``verlinkt`` hinter die Chunks der besten ``QUELLEN`` Notizen (ohne Doppelte)."""
    if not verlinkt:
        return treffer
    notizen: list[str] = []
    grenze = len(treffer)
    for i, h in enumerate(treffer):
        if h.chunk.path not in notizen:
            if len(notizen) == QUELLEN:
                grenze = i
                break
            notizen.append(h.chunk.path)
    # Gleicher Score wie der letzte Treffer davor: Die Liste bleibt absteigend sortiert, und
    # BM25-Werte vermischen sich nicht mit RRF- oder Kosinus-Werten.
    score = treffer[grenze - 1].score if grenze else 0.0
    neu = [Hit(h.chunk, score) for h in verlinkt if h.chunk.path not in notizen]
    pfade = {h.chunk.path for h in neu}
    rest = [h for h in treffer[grenze:] if h.chunk.path not in pfade]
    return [*treffer[:grenze], *neu, *rest]
