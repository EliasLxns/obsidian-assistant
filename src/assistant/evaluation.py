"""Eval: misst, ob die Suche die erwarteten Notizen findet (Treffer@1 und Treffer@k).

Treffer@k zählt, wenn die erwartete Notiz unter den ersten k Notizen ist.
Bei ``typ: mehrere`` müssen so viele erwartete Notizen unter den ersten k sein,
wie hineinpassen: bei k=1 also eine, bei k=5 alle (höchstens fünf).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from assistant.retrieval.search import Retriever

TYPEN = ("exakt", "umschreibung", "mehrere")


@dataclass(frozen=True)
class EvalQuestion:
    frage: str
    erwartet: tuple[str, ...]
    typ: str


@dataclass(frozen=True)
class QuestionResult:
    question: EvalQuestion
    found: tuple[str, ...]  # Notizpfade in Trefferreihenfolge

    def hit_at(self, k: int) -> bool:
        oben = set(self.found[:k])
        noetig = min(k, len(self.question.erwartet))
        return sum(1 for e in self.question.erwartet if e in oben) >= noetig

    def rank(self) -> int | None:
        """Position (ab 1) der ersten erwarteten Notiz, ``None`` wenn nicht gefunden."""
        for pos, pfad in enumerate(self.found, start=1):
            if pfad in self.question.erwartet:
                return pos
        return None


@dataclass(frozen=True)
class EvalResult:
    results: list[QuestionResult]
    k: int

    def rate(self, k: int, typ: str | None = None) -> float:
        auswahl = [r for r in self.results if typ is None or r.question.typ == typ]
        if not auswahl:
            return 0.0
        return sum(r.hit_at(k) for r in auswahl) / len(auswahl)


def load_questions(path: Path) -> list[EvalQuestion]:
    daten = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(daten, list):
        raise ValueError(f"{path}: erwartet wird eine Liste von Fragen")
    fragen: list[EvalQuestion] = []
    for eintrag in cast(list[dict[str, Any]], daten):
        erwartet: object = eintrag["erwartet"]
        ziele = (
            tuple(str(e) for e in cast(list[object], erwartet))
            if isinstance(erwartet, list)
            else (str(erwartet),)
        )
        typ = str(eintrag.get("typ", "exakt"))
        if typ not in TYPEN:
            raise ValueError(f"Unbekannter typ '{typ}' bei Frage: {eintrag['frage']}")
        fragen.append(EvalQuestion(frage=str(eintrag["frage"]), erwartet=ziele, typ=typ))
    return fragen


def evaluate(retriever: Retriever, questions: Sequence[EvalQuestion], k: int = 5) -> EvalResult:
    ergebnisse = [
        QuestionResult(q, tuple(h.chunk.path for h in retriever.search_notes(q.frage, k)))
        for q in questions
    ]
    return EvalResult(ergebnisse, k)


def _prozent(wert: float) -> str:
    return f"{wert * 100:.0f} %"


def format_table(result: EvalResult) -> str:
    """Ergebnis als Markdown-Tabelle, im Terminal lesbar und direkt ins Handbuch kopierbar."""
    k = result.k
    zeilen = [
        f"| Typ | Fragen | Treffer@1 | Treffer@{k} |",
        "|---|---:|---:|---:|",
    ]
    for typ in TYPEN:
        anzahl = sum(1 for r in result.results if r.question.typ == typ)
        if anzahl:
            zeilen.append(
                f"| {typ} | {anzahl} | {_prozent(result.rate(1, typ))} | "
                f"{_prozent(result.rate(k, typ))} |"
            )
    zeilen.append(
        f"| **gesamt** | {len(result.results)} | **{_prozent(result.rate(1))}** | "
        f"**{_prozent(result.rate(k))}** |"
    )
    return "\n".join(zeilen)


def format_details(result: EvalResult) -> str:
    zeilen = ["| Frage | Typ | Rang | Treffer@k |", "|---|---|---:|:---:|"]
    for r in result.results:
        rang = r.rank()
        zeilen.append(
            f"| {r.question.frage} | {r.question.typ} | {rang if rang else '–'} | "
            f"{'✓' if r.hit_at(result.k) else '✗'} |"
        )
    return "\n".join(zeilen)
