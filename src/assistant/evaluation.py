"""Eval: misst, ob die Suche die erwarteten Notizen findet (Treffer@1 und Treffer@k).

Treffer@k zählt, wenn die erwartete Notiz unter den ersten k Notizen ist.
Bei ``typ: mehrere`` und ``verlinkt`` (die zweite Notiz ist über einen Wikilink der ersten
erreichbar) müssen so viele erwartete Notizen unter den ersten k sein,
wie hineinpassen: bei k=1 also eine, bei k=5 alle (höchstens fünf).

``typ: ohne_antwort`` sind Fragen, zu denen der Vault nichts sagt (``erwartet`` fehlt oder ist
leer). Sie zählen nicht in Treffer@k. Gemessen wird stattdessen der beste Score: Liegt er bei
Fragen ohne Antwort klar unter dem von beantwortbaren Fragen, lässt sich eine Schwelle setzen,
unter der der Assistent „nichts gefunden“ sagt. Aussagekräftig ist das nur mit festen Scores
(``--modus vektor``: Kosinus); RRF-Werte in ``hybrid`` hängen nur von den Plätzen ab.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any, cast

import yaml

from assistant.retrieval.search import Retriever

TYPEN = ("exakt", "umschreibung", "mehrere", "verlinkt", "ohne_antwort")
OHNE_ANTWORT = "ohne_antwort"


@dataclass(frozen=True)
class EvalQuestion:
    frage: str
    erwartet: tuple[str, ...]  # leer bei ohne_antwort
    typ: str

    @property
    def beantwortbar(self) -> bool:
        return self.typ != OHNE_ANTWORT


@dataclass(frozen=True)
class QuestionResult:
    question: EvalQuestion
    found: tuple[str, ...]  # Notizpfade in Trefferreihenfolge
    scores: tuple[float, ...] = ()  # Score je gefundener Notiz, gleiche Reihenfolge

    @property
    def best_score(self) -> float | None:
        return self.scores[0] if self.scores else None

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

    @property
    def beantwortbar(self) -> list[QuestionResult]:
        return [r for r in self.results if r.question.beantwortbar]

    @property
    def ohne_antwort(self) -> list[QuestionResult]:
        return [r for r in self.results if not r.question.beantwortbar]

    def rate(self, k: int, typ: str | None = None) -> float:
        """Treffer@k, ohne ``typ`` über alle beantwortbaren Fragen."""
        auswahl = [r for r in self.beantwortbar if typ is None or r.question.typ == typ]
        if not auswahl:
            return 0.0
        return sum(r.hit_at(k) for r in auswahl) / len(auswahl)

    def unter_schwelle(self, schwelle: float, *, beantwortbar: bool) -> tuple[int, int]:
        """(Anzahl mit bestem Score unter ``schwelle``, Anzahl Fragen) für eine der Gruppen.

        Bei Fragen ohne Antwort ist „unter der Schwelle“ richtig (abgelehnt), bei
        beantwortbaren falsch (die Antwort wäre unterdrückt worden). Ohne Treffer zählt
        eine Frage als unter der Schwelle.
        """
        gruppe = self.beantwortbar if beantwortbar else self.ohne_antwort
        unter = sum(1 for r in gruppe if r.best_score is None or r.best_score < schwelle)
        return unter, len(gruppe)


def load_questions(path: Path) -> list[EvalQuestion]:
    daten = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(daten, list):
        raise ValueError(f"{path}: erwartet wird eine Liste von Fragen")
    fragen: list[EvalQuestion] = []
    for eintrag in cast(list[dict[str, Any]], daten):
        erwartet: object = eintrag.get("erwartet")
        if erwartet is None:
            ziele: tuple[str, ...] = ()
        elif isinstance(erwartet, list):
            ziele = tuple(str(e) for e in cast(list[object], erwartet))
        else:
            ziele = (str(erwartet),)
        typ = str(eintrag.get("typ", "exakt"))
        if typ not in TYPEN:
            raise ValueError(f"Unbekannter typ '{typ}' bei Frage: {eintrag['frage']}")
        if (typ == OHNE_ANTWORT) != (not ziele):
            raise ValueError(
                f"Frage '{eintrag['frage']}': 'erwartet' muss bei typ {OHNE_ANTWORT} leer "
                "sein und sonst mindestens eine Notiz nennen"
            )
        fragen.append(EvalQuestion(frage=str(eintrag["frage"]), erwartet=ziele, typ=typ))
    return fragen


def evaluate(retriever: Retriever, questions: Sequence[EvalQuestion], k: int = 5) -> EvalResult:
    ergebnisse: list[QuestionResult] = []
    for q in questions:
        hits = retriever.search_notes(q.frage, k)
        ergebnisse.append(
            QuestionResult(q, tuple(h.chunk.path for h in hits), tuple(h.score for h in hits))
        )
    return EvalResult(ergebnisse, k)


def _prozent(wert: float) -> str:
    return f"{wert * 100:.0f} %"


def _score(wert: float | None) -> str:
    return "–" if wert is None else f"{wert:.3f}"


def format_table(result: EvalResult, schwelle: float | None = None) -> str:
    """Ergebnis als Markdown-Tabelle, im Terminal lesbar und direkt ins Handbuch kopierbar.

    Gibt es Fragen ohne Antwort, folgt darunter der Vergleich der besten Scores und, mit
    ``schwelle``, wie viele Fragen eine Schwelle richtig ablehnen bzw. fälschlich unterdrücken.
    """
    k = result.k
    zeilen = [
        f"| Typ | Fragen | Treffer@1 | Treffer@{k} |",
        "|---|---:|---:|---:|",
    ]
    for typ in TYPEN:
        anzahl = sum(1 for r in result.results if r.question.typ == typ)
        if not anzahl:
            continue
        if typ == OHNE_ANTWORT:
            zeilen.append(f"| {typ} | {anzahl} | – | – |")
        else:
            zeilen.append(
                f"| {typ} | {anzahl} | {_prozent(result.rate(1, typ))} | "
                f"{_prozent(result.rate(k, typ))} |"
            )
    zeilen.append(
        f"| **gesamt** | {len(result.beantwortbar)} | **{_prozent(result.rate(1))}** | "
        f"**{_prozent(result.rate(k))}** |"
    )
    if result.ohne_antwort:
        zeilen += ["", *_score_vergleich(result, schwelle)]
    return "\n".join(zeilen)


def _score_vergleich(result: EvalResult, schwelle: float | None) -> list[str]:
    def beste(gruppe: list[QuestionResult]) -> list[float]:
        return sorted(r.best_score for r in gruppe if r.best_score is not None)

    mit, ohne = beste(result.beantwortbar), beste(result.ohne_antwort)
    zeilen = [
        "Bester Score je Frage (gesamt zählt nur Fragen mit Antwort):",
        "",
        "| Gruppe | Fragen | niedrigster | Median | höchster |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, werte, n in (
        ("mit Antwort", mit, len(result.beantwortbar)),
        ("ohne Antwort", ohne, len(result.ohne_antwort)),
    ):
        unten, mitte, oben = (werte[0], median(werte), werte[-1]) if werte else (None,) * 3
        zeilen.append(f"| {name} | {n} | {_score(unten)} | {_score(mitte)} | {_score(oben)} |")
    if schwelle is not None:
        abgelehnt, n_ohne = result.unter_schwelle(schwelle, beantwortbar=False)
        verloren, n_mit = result.unter_schwelle(schwelle, beantwortbar=True)
        zeilen += [
            "",
            f"Schwelle {schwelle:g}: {abgelehnt} von {n_ohne} Fragen ohne Antwort abgelehnt, "
            f"{verloren} von {n_mit} Fragen mit Antwort fälschlich unterdrückt.",
        ]
    return zeilen


def format_details(result: EvalResult) -> str:
    zeilen = [
        "| Frage | Typ | Rang | Treffer@k | bester Score |",
        "|---|---|---:|:---:|---:|",
    ]
    for r in result.results:
        rang = r.rank()
        treffer = ("✓" if r.hit_at(result.k) else "✗") if r.question.beantwortbar else "–"
        zeilen.append(
            f"| {r.question.frage} | {r.question.typ} | {rang if rang else '–'} | "
            f"{treffer} | {_score(r.best_score)} |"
        )
    zeilen += [
        "",
        "Rang: Platz der ersten erwarteten Notiz. Bei „mehrere“ und „verlinkt“ zählt ein "
        f"Treffer erst, wenn alle erwarteten Notizen (höchstens {result.k}) unter den ersten "
        f"{result.k} sind.",
    ]
    return "\n".join(zeilen)
