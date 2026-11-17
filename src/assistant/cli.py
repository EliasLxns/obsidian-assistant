"""Kommandozeile: ``assistant index | ask | eval``.

Phase 0: Nur das Gerüst. Die Befehle werden in Phase 1 implementiert.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assistant",
        description="Lokaler RAG-Assistent für einen Obsidian-Vault.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Vault einlesen und indexieren")
    p_index.add_argument("pfad", help="Pfad zum Vault, z. B. demo_vault/")

    p_ask = sub.add_parser("ask", help="Frage an den Vault stellen")
    p_ask.add_argument("frage", help="Die Frage in Anführungszeichen")

    p_eval = sub.add_parser("eval", help="Trefferquote mit dem Eval-Set messen")
    p_eval.add_argument(
        "--fragen",
        default="eval/questions.yaml",
        help="Pfad zum Eval-Set (Standard: eval/questions.yaml)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"'{args.command}' ist noch nicht implementiert (kommt in Phase 1).", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
