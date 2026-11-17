"""PostToolUse-Hook: prüft jede Python-Datei direkt nach einer Änderung.

Läuft nach Edit/Write. Bei einer .py-Datei:
1. `ruff check --fix` und `ruff format` räumen auf, was automatisch geht.
2. `ruff check` und `pyright` melden, was übrig bleibt.

Bleibt ein Fehler, endet der Hook mit Code 2. Claude bekommt die Meldung
dann direkt neben dem Ergebnis des Werkzeugs und behebt sie sofort, statt
erst in der GitHub Action davon zu erfahren. Fehlt ein Werkzeug (z. B. in
einer frischen Umgebung ohne `pip install -e ".[dev]"`), wird es übersprungen.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

MAX_OUTPUT = 4000


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120, check=False)


def project_root(file: Path) -> Path:
    for parent in [file.parent, *file.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    return file.parent


def tool(name: str, root: Path) -> str | None:
    """Werkzeug zuerst in der .venv des Projekts suchen, dann im PATH.

    Unter Windows ist die .venv beim Hook-Aufruf meist nicht aktiviert.
    """
    for folder in (root / ".venv" / "Scripts", root / ".venv" / "bin"):
        found = shutil.which(name, path=str(folder))
        if found:
            return found
    return shutil.which(name)


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    raw = (event.get("tool_input") or {}).get("file_path")
    if not isinstance(raw, str) or not raw.endswith(".py"):
        return 0
    file = Path(raw)
    if not file.exists():
        return 0
    root = project_root(file)

    problems: list[str] = []
    ruff = tool("ruff", root)
    if ruff:
        run([ruff, "check", "--fix", "--quiet", str(file)], root)
        run([ruff, "format", "--quiet", str(file)], root)
        left = run([ruff, "check", "--quiet", str(file)], root)
        if left.returncode != 0:
            problems.append("ruff:\n" + (left.stdout + left.stderr).strip())
    pyright = tool("pyright", root)
    if pyright:
        typed = run([pyright, str(file)], root)
        if typed.returncode != 0:
            problems.append("pyright:\n" + (typed.stdout + typed.stderr).strip())

    if not problems:
        return 0
    report = "\n\n".join(problems)[:MAX_OUTPUT]
    print(f"Prüfung von {file.name} fehlgeschlagen. Bitte beheben:\n\n{report}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
