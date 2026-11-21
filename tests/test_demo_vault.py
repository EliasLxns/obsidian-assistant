"""Prüft, dass Demo-Vault und Eval-Set zusammenpassen."""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "demo_vault"
QUESTIONS = ROOT / "eval" / "questions.yaml"
SCHWER = ROOT / "eval" / "schwer.yaml"
EVAL_SETS = pytest.mark.parametrize("datei", [QUESTIONS, SCHWER], ids=["standard", "schwer"])


def _notizen() -> list[Path]:
    return sorted(p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts)


def _fragen(datei: Path = QUESTIONS) -> list[dict[str, Any]]:
    data = yaml.safe_load(datei.read_text(encoding="utf-8"))
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


def test_eval_set_hat_23_fragen() -> None:
    assert len(_fragen()) == 23


def test_schweres_set_hat_alle_typen() -> None:
    fragen = _fragen(SCHWER)
    assert len(fragen) == 30
    typen = {e["typ"] for e in fragen}
    assert typen == {"umschreibung", "mehrere", "verlinkt", "ohne_antwort"}
    assert any(len(e["erwartet"]) == 3 for e in fragen if e["typ"] == "mehrere")


def test_keine_frage_doppelt() -> None:
    alle = [e["frage"] for d in (QUESTIONS, SCHWER) for e in _fragen(d)]
    assert len(alle) == len(set(alle))


@EVAL_SETS
def test_verlinkte_fragen_haben_einen_wikilink(datei: Path) -> None:
    """Bei typ: verlinkt verlinkt die erste erwartete Notiz auf die zweite."""
    for eintrag in _fragen(datei):
        if eintrag["typ"] != "verlinkt":
            continue
        erste, zweite = cast(list[str], eintrag["erwartet"])[:2]
        text = (VAULT / erste).read_text(encoding="utf-8")
        assert f"[[{Path(zweite).stem}" in text, eintrag["frage"]


@EVAL_SETS
def test_erwartete_notizen_existieren(datei: Path) -> None:
    for eintrag in _fragen(datei):
        assert isinstance(eintrag["frage"], str) and eintrag["frage"].strip()
        if eintrag["typ"] == "ohne_antwort":
            assert not eintrag.get("erwartet"), eintrag["frage"]
            continue
        erwartet = eintrag["erwartet"]
        ziele: list[str] = cast(list[str], erwartet) if isinstance(erwartet, list) else [erwartet]
        for ziel in ziele:
            assert (VAULT / ziel).is_file(), f"{eintrag['frage']}: {ziel} fehlt"
