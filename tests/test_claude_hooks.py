"""Tests für die Claude-Code-Hooks in .claude/hooks/.

Die Hooks laufen als eigene Prozesse und lesen ein JSON-Ereignis von stdin.
Die Tests machen es genauso.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"


def run_hook(name: str, event: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOKS / name)],
        input=json.dumps(event),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "Schreib Commit-Messages ab jetzt immer auf Deutsch",
        "Nutze nie print() für Logs",
        "Merk dir: Eval-Ergebnisse kommen nach docs/",
        "Regel: keine echten Notizen in Tests",
        "Nicht so, nimm stattdessen pathlib",
        "From now on, always run ruff",
    ],
)
def test_regel_wird_erkannt(prompt: str) -> None:
    result = run_hook("capture_rules.py", {"prompt": prompt})
    assert result.returncode == 0
    output: dict[str, dict[str, str]] = json.loads(result.stdout)
    assert "## Regeln" in output["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize(
    "prompt",
    ["Wie weit bist du mit dem Chunker?", "Starte die Tests", "/code-review", ""],
)
def test_normale_nachricht_bleibt_still(prompt: str) -> None:
    result = run_hook("capture_rules.py", {"prompt": prompt})
    assert result.returncode == 0
    assert result.stdout == ""


def test_check_python_ignoriert_andere_dateien(tmp_path: Path) -> None:
    note = tmp_path / "notiz.md"
    note.write_text("# Notiz\n", encoding="utf-8")
    result = run_hook("check_python.py", {"tool_input": {"file_path": str(note)}})
    assert result.returncode == 0


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff nicht installiert")
def test_check_python_formatiert_und_meldet_fehler(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    module = tmp_path / "modul.py"
    module.write_text("x=1\nprint(undefiniert)\n", encoding="utf-8")
    result = run_hook("check_python.py", {"tool_input": {"file_path": str(module)}})
    assert result.returncode == 2
    assert "undefiniert" in result.stderr
    assert module.read_text(encoding="utf-8").startswith("x = 1")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff nicht installiert")
def test_check_python_sauber_ist_still(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\n", encoding="utf-8")
    module = tmp_path / "sauber.py"
    module.write_text('def gruss() -> str:\n    return "hallo"\n', encoding="utf-8")
    result = run_hook("check_python.py", {"tool_input": {"file_path": str(module)}})
    assert result.returncode == 0, result.stderr
