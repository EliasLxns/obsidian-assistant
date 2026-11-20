"""BM25: klassische Stichwortsuche, ergänzt die Vektorsuche.

Vektoren finden Umschreibungen („Container starten“ → ``docker compose up``), verfehlen aber
gern exakte, seltene Begriffe wie ``ITBS``, ``11434`` oder ``unless-stopped``. BM25 zählt
genau solche Begriffe und gewichtet seltene stärker als häufige.

Formel je Begriff ``t`` der Anfrage und Chunk ``d``::

    idf(t) * f(t, d) * (k1 + 1) / (f(t, d) + k1 * (1 - b + b * |d| / avgdl))

``f`` ist die Häufigkeit im Chunk, ``|d|`` die Länge in Wörtern, ``avgdl`` die mittlere
Länge. ``k1`` dämpft Wiederholungen, ``b`` gleicht lange Chunks aus.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from assistant.index.store import Hit
from assistant.ingest.chunker import Chunk

_WORT = re.compile(r"\w+")

# Häufige deutsche Wörter tragen keine Bedeutung für die Suche.
STOPPWOERTER = frozenset(
    """
    der die das den dem des ein eine einer eines einem einen und oder aber nicht kein keine ist
    sind war waren wird werden wurde sein hat habe haben hatte ich du er sie es wir ihr mein
    meine meinen meinem dich mich mir dir sich man mit von zu zum zur im in an am auf aus bei
    für über unter vor nach bis um wie was wer wo wann warum welche welcher welches welchen
    wieso dass so auch noch nur schon sehr mehr als dann wenn ob kann können muss soll sollte
    will würde gibt mal ja nein hier da dort diese dieser dieses diesen
    """.split()  # noqa: SIM905 (als Liste wäre das hundert Zeilen lang)
)

# Endungen, die abgeschnitten werden, damit „Container“ und „Containern“ zusammenfinden.
# Bewusst grob (kein echter Stemmer), längste Endung zuerst.
_ENDUNGEN = ("ungen", "ung", "ern", "en", "er", "es", "em", "e", "n", "s")


def stamm(wort: str) -> str:
    for endung in _ENDUNGEN:
        if len(wort) - len(endung) >= 4 and wort.endswith(endung):
            return wort[: -len(endung)]
    return wort


def woerter(text: str) -> list[str]:
    """Kleinschreibung, Stoppwörter raus, grob auf den Stamm gekürzt.

    ``unless-stopped`` wird zu ``unless`` und ``stopped``, Zahlen wie ``11434`` bleiben.
    """
    return [stamm(w) for w in _WORT.findall(text.casefold()) if w not in STOPPWOERTER]


class Bm25:
    def __init__(self, chunks: Sequence[Chunk], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = list(chunks)
        self.k1 = k1
        self.b = b
        # Titel und Überschrift zählen mit, wie beim Einbetten.
        self._tf = [Counter(woerter(c.embed_text)) for c in self.chunks]
        self._laenge = [sum(tf.values()) for tf in self._tf]
        self._avgdl = sum(self._laenge) / len(self._laenge) if self._laenge else 0.0
        df: Counter[str] = Counter()
        for tf in self._tf:
            df.update(tf.keys())
        n = len(self.chunks)
        # BM25+-Variante des idf (immer > 0), damit sehr häufige Wörter nicht negativ zählen.
        self._idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def search(self, query: str, k: int) -> list[Hit]:
        """Die ``k`` besten Chunks, ``score`` ist der BM25-Wert (nur Treffer mit Score > 0)."""
        begriffe = set(woerter(query))
        if not begriffe or not self.chunks:
            return []
        hits: list[Hit] = []
        for chunk, tf, laenge in zip(self.chunks, self._tf, self._laenge, strict=True):
            score = 0.0
            for t in begriffe:
                f = tf.get(t, 0)
                if f:
                    norm = self.k1 * (1 - self.b + self.b * laenge / self._avgdl)
                    score += self._idf[t] * f * (self.k1 + 1) / (f + norm)
            if score > 0:
                hits.append(Hit(chunk, score))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]
