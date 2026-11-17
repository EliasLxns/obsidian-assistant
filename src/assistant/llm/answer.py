"""Frage → passende Chunks → Prompt → Antwort mit nummerierten Quellen."""

from __future__ import annotations

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
    hits = retriever.search(question, k)
    if not hits:
        return Answer(KEINE_TREFFER, [])
    text = llm.generate(build_answer_prompt(question, hits), system=SYSTEM_PROMPT)
    return Answer(text, hits)
