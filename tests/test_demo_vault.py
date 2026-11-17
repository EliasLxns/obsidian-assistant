"""Prüft, dass Demo-Vault und Eval-Set zusammenpassen."""

from pathlib import Path
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "demo_vault"
QUESTIONS = ROOT / "eval" / "questions.yaml"


def _notizen() -> list[Path]:
    return sorted(p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts)


def _fragen() -> list[dict[str, Any]]:
    data = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return cast(list[dict[str, Any]], data)


def test_vault_hat_20_bis_30_notizen() -> None:
    assert 20 <= len(_notizen()) <= 30


def test_jede_notiz_hat_frontmatter() -> None:
    for notiz in _notizen():
        text = notiz.read_text(encoding="utf-8")
        assert text.startswith("---\n"), notiz
        _, front, _ = text.split("---\n", 2)
        assert isinstance(yaml.safe_load(front), dict), notiz


def test_wikilinks_zeigen_auf_vorhandene_notizen() -> None:
    import re

    namen = {p.stem for p in _notizen()}
    for notiz in _notizen():
        for ziel in re.findall(r"\[\[([^\]|#]+)", notiz.read_text(encoding="utf-8")):
            assert ziel.strip() in namen, f"{notiz.name}: [[{ziel}]] fehlt"


def test_eval_set_hat_20_fragen() -> None:
    assert len(_fragen()) == 20


def test_erwartete_notizen_existieren() -> None:
    for eintrag in _fragen():
        assert isinstance(eintrag["frage"], str) and eintrag["frage"].strip()
        erwartet = eintrag["erwartet"]
        ziele: list[str] = cast(list[str], erwartet) if isinstance(erwartet, list) else [erwartet]
        for ziel in ziele:
            assert (VAULT / ziel).is_file(), f"{eintrag['frage']}: {ziel} fehlt"
