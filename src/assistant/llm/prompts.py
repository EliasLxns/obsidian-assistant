"""Prompts für Antworten mit Quellen. Bewusst kurz und auf Deutsch."""

from __future__ import annotations

from collections.abc import Sequence

from assistant.index.store import Hit

SYSTEM_PROMPT = """Du beantwortest Fragen ausschließlich anhand der Notizen, die dir gegeben werden.
Regeln:
- Antworte auf Deutsch, knapp und konkret.
- Belege jede Aussage mit der Nummer der Quelle in eckigen Klammern, z. B. [1] oder [2][3].
- Steht die Antwort nicht in den Notizen, sage das ehrlich. Erfinde nichts."""


def format_context(hits: Sequence[Hit]) -> str:
    bloecke: list[str] = []
    for nr, hit in enumerate(hits, start=1):
        c = hit.chunk
        ort = c.title if not c.heading else f"{c.title} – {c.heading}"
        bloecke.append(f"[{nr}] {ort} ({c.path})\n{c.text}")
    return "\n\n---\n\n".join(bloecke)


def build_answer_prompt(question: str, hits: Sequence[Hit]) -> str:
    return f"Notizen:\n\n{format_context(hits)}\n\nFrage: {question}\n\nAntwort:"
