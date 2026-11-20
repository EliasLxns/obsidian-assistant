"""Prompts für Antworten mit Quellen. Bewusst kurz und auf Deutsch."""

from __future__ import annotations

from collections.abc import Sequence

from assistant.index.store import Hit

SYSTEM_PROMPT = """Du beantwortest Fragen ausschließlich anhand der Notizen, die dir gegeben werden.
Die Notizen hat die fragende Person selbst geschrieben.
Regeln:
- Antworte auf Deutsch, knapp und konkret. Sprich die Person mit „du“ an, nie mit „Sie“.
- Schreibe nur, was so in den Notizen steht. Erfinde keine Gründe, Wirkungen oder Ratschläge
  dazu, auch wenn sie plausibel klingen.
- Belege jeden Satz mit der Nummer der Quelle in eckigen Klammern, z. B. [1] oder [2][3].
  Nenne nur Quellen, in denen die Aussage wirklich steht.
- Jede Information nur einmal. Keine Nachsätze wie „wie in den Notizen belegt“.
- Steht die Antwort nicht in den Notizen, sage das ehrlich."""


def format_context(hits: Sequence[Hit]) -> str:
    bloecke: list[str] = []
    for nr, hit in enumerate(hits, start=1):
        c = hit.chunk
        ort = c.title if not c.heading else f"{c.title} – {c.heading}"
        bloecke.append(f"[{nr}] {ort} ({c.path})\n{c.text}")
    return "\n\n---\n\n".join(bloecke)


def build_answer_prompt(question: str, hits: Sequence[Hit]) -> str:
    return f"Notizen:\n\n{format_context(hits)}\n\nFrage: {question}\n\nAntwort:"
