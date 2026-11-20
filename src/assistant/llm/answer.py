"""Frage → passende Chunks → Prompt → Antwort mit nummerierten Quellen."""

from __future__ import annotations

import re
from dataclasses import dataclass

from assistant.index.store import Hit
from assistant.llm.client import LLM
from assistant.llm.prompts import SYSTEM_PROMPT, build_answer_prompt
from assistant.retrieval.search import Retriever

KEINE_TREFFER = "Dazu habe ich in deinen Notizen nichts gefunden."


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Hit]  # Reihenfolge entspricht den Nummern [1], [2], … im Text


def answer_question(question: str, retriever: Retriever, llm: LLM, k: int = 5) -> Answer:
    return answer_from_hits(question, retriever.search(question, k), llm)


def answer_from_hits(question: str, hits: list[Hit], llm: LLM) -> Answer:
    """Antwort aus schon gefundenen Chunks (z. B. gefiltert wie im Nachtjob)."""
    if not hits:
        return Answer(KEINE_TREFFER, [])
    text = llm.generate(build_answer_prompt(question, hits), system=SYSTEM_PROMPT)
    return Answer(*nur_zitierte(text, hits))


# [1], [2, 3], [2-4], [2–4]: Zahlen, durch Komma oder Bindestrich getrennt
_ZITAT = re.compile(r"\[(\d+(?:\s*[,–-]\s*\d+)*)\]")


def _nummern(inhalt: str) -> list[int]:
    nummern: list[int] = []
    for teil in inhalt.split(","):
        von, _, bis = teil.replace("–", "-").partition("-")
        a = int(von)
        b = int(bis) if bis.strip() else a
        nummern += range(a, b + 1) if b - a < 20 else [a, b]
    return nummern


def nur_zitierte(text: str, hits: list[Hit]) -> tuple[str, list[Hit]]:
    """Behält nur Quellen, die im Text zitiert werden, und nummeriert sie neu (1, 2, …).

    Als Zitat gilt eine Klammer, deren Nummern alle zu einer Quelle passen (``[2]``,
    ``[2, 3]``, ``[2-3]``). Andere Klammern wie ``werte[0]`` oder ``[2026]`` bleiben stehen.
    Zitiert das Modell gar nichts, bleiben alle Quellen stehen: Dann soll man sehen können,
    woraus die Antwort stammt.
    """

    def zitat(m: re.Match[str]) -> list[int] | None:
        nummern = _nummern(m.group(1))
        return nummern if all(1 <= n <= len(hits) for n in nummern) else None

    reihenfolge: list[int] = []
    for m in _ZITAT.finditer(text):
        for n in zitat(m) or []:
            if n not in reihenfolge:
                reihenfolge.append(n)
    if not reihenfolge:
        return text, hits
    neu = {alt: i for i, alt in enumerate(reihenfolge, start=1)}

    def ersetzen(m: re.Match[str]) -> str:
        nummern = zitat(m)
        if nummern is None:
            return m.group(0)
        return "".join(f"[{neu[n]}]" for n in dict.fromkeys(nummern))

    return _ZITAT.sub(ersetzen, text), [hits[alt - 1] for alt in reihenfolge]
