"""UserPromptSubmit-Hook: hält Regeln aus dem Chat in der CLAUDE.md fest.

Erkennt in deiner Nachricht Formulierungen, die nach einer dauerhaften Regel
oder Korrektur klingen („immer“, „nie“, „ab jetzt“, „merk dir“, „Regel:“ …).
Dann bekommt Claude einen Hinweis, die Regel als eine Zeile unter
„## Regeln“ in der CLAUDE.md einzutragen und das kurz zu bestätigen.

Der Hook selbst schreibt nichts und ruft kein Modell auf. Er kostet also
keine Tokens, solange keine Regel erkannt wird. Ob es wirklich eine dauerhafte
Regel ist, entscheidet Claude.
"""

from __future__ import annotations

import json
import re
import sys

TRIGGERS = [
    r"\bimmer\b",
    r"\bnie\b",
    r"\bniemals\b",
    r"\bab (jetzt|sofort|heute)\b",
    r"\bkünftig\b",
    r"\bin zukunft\b",
    r"\bmerk(e)? dir\b",
    r"\bregel\b",
    r"\bnicht (mehr|so)\b",
    r"\bstattdessen\b",
    r"\blass das\b",
    r"\bhör auf\b",
    r"\bdas ist falsch\b",
    r"\bich (will|möchte) (nicht|kein)",
    r"\bbitte (keine?n?|nicht)\b",
    r"\balways\b",
    r"\bnever\b",
    r"\bfrom now on\b",
    r"\bremember\b",
    r"\bdon'?t\b",
]
PATTERN = re.compile("|".join(TRIGGERS), re.IGNORECASE)

HINT = (
    "Die Nachricht enthält eventuell eine dauerhafte Regel oder Korrektur. "
    "Wenn sie für dieses Projekt künftig gelten soll (nicht nur für diese eine Aufgabe), "
    "trage sie als eine kurze Zeile unter '## Regeln' in die CLAUDE.md ein, im Stil der "
    "vorhandenen Zeilen, und schreib in deiner Antwort in einem Satz, welche Regel du "
    "festgehalten hast. Prüfe vorher, ob die Regel schon dasteht oder einer bestehenden "
    "widerspricht; dann frag nach, statt zu raten. Keine privaten Daten oder echten "
    "Notizinhalte eintragen, das Repo ist öffentlich. Ist es keine dauerhafte Regel, "
    "ignoriere diesen Hinweis."
)


def is_rule(prompt: str) -> bool:
    text = prompt.strip()
    if not text or text.startswith("/") or len(text) > 3000:
        return False
    return PATTERN.search(text) is not None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    prompt = event.get("prompt")
    if not isinstance(prompt, str) or not is_rule(prompt):
        return 0
    output = {
        "hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": HINT}
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
