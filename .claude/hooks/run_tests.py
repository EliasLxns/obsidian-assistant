"""Stop-Hook: lässt Claude nicht „fertig“ sagen, solange Tests rot sind.

Läuft, wenn Claude eine Antwort beenden will. Nur wenn im Arbeitsbaum
Python-Dateien oder die pyproject.toml geändert sind, startet `pytest -x -q`
(die Tests laufen ohne Ollama und sind schnell).

- Tests grün: Claude darf aufhören.
- Tests rot: Der Hook blockiert einmal und gibt Claude die Ausgabe zum Beheben.
- Immer noch rot nach dieser einen Runde: Claude darf aufhören, du bekommst
  aber eine sichtbare Warnung. So entsteht keine Endlosschleife.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 4000


def changed_python_files(root: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in status.stdout.splitlines():
        path = line[3:].strip().strip('"')
        if path.endswith(".py") or path.endswith("pyproject.toml"):
            return True
    return False


def python_with_pytest(root: Path) -> str | None:
    """Sucht ein Python, in dem pytest und das Projekt installiert sind.

    Zuerst die .venv des Projekts, dann das Python, das den Hook ausführt.
    """
    candidates = [
        root / ".venv" / "bin" / "python",
        root / ".venv" / "Scripts" / "python.exe",
        Path(sys.executable),
    ]
    for python in candidates:
        if not python.exists():
            continue
        probe = subprocess.run(
            [str(python), "-c", "import pytest"], capture_output=True, check=False
        )
        if probe.returncode == 0:
            return str(python)
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        event = {}
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".")
    if not changed_python_files(root):
        return 0
    python = python_with_pytest(root)
    if python is None:
        return 0

    result = subprocess.run(
        [python, "-m", "pytest", "-x", "-q", "--no-header"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    # Code 5 heißt „keine Tests gefunden“, das ist kein Fehler.
    if result.returncode in (0, 5):
        return 0

    output = (result.stdout + result.stderr).strip()[-MAX_OUTPUT:]
    if event.get("stop_hook_active"):
        print(
            json.dumps(
                {"systemMessage": "Achtung: pytest schlägt weiterhin fehl."}, ensure_ascii=False
            )
        )
        return 0
    print(
        "pytest schlägt fehl. Behebe die Ursache, bevor du die Antwort beendest. "
        "Tests nie überspringen oder abschwächen.\n\n" + output,
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
