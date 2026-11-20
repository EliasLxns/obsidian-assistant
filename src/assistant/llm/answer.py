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


_ZITAT = re.compile(r"\[(\d+)\]")


def nur_zitierte(text: str, hits: list[Hit]) -> tuple[str, list[Hit]]:
    """Behält nur Quellen, die im Text zitiert werden, und nummeriert sie neu (1, 2, …).

    Nummern ohne passende Quelle (das Modell zählt manchmal falsch) fallen aus dem Text.
    Zitiert das Modell gar nichts, bleiben alle Quellen stehen: Dann soll man sehen können,
    woraus die Antwort stammt.
    """
    reihenfolge: list[int] = []
    for m in _ZITAT.finditer(text):
        nr = int(m.group(1))
        if 1 <= nr <= len(hits) and nr not in reihenfolge:
            reihenfolge.append(nr)
    if not reihenfolge:
        return text, hits
    neu = {alt: i for i, alt in enumerate(reihenfolge, start=1)}

    def ersetzen(m: re.Match[str]) -> str:
        nr = int(m.group(1))
        return f"[{neu[nr]}]" if nr in neu else ""

    return _ZITAT.sub(ersetzen, text), [hits[alt - 1] for alt in reihenfolge]
