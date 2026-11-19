"""Reine Hilfsfunktionen fürs Dashboard: Texte, Zeiten, Wikilink-Chips.

Ohne ``streamlit``, damit sie sich mit pytest einfach testen lassen.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import PurePosixPath

# Art eines Eintrags → (Beschriftung, Badge-Farbe aus dem Theme)
ARTEN: dict[str, tuple[str, str]] = {
    "einsortiert": ("Einsortiert", "green"),
    "beantwortet": ("Beantwortet", "green"),
    "pruefen": ("Prüfen", "orange"),
    "fehler": ("Fehler", "red"),
    "frage": ("Frage offen", "blue"),
    "notiz": ("Wartet auf die Nacht", "gray"),
}

_MD_SONDERZEICHEN = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")


def art_text(art: str) -> str:
    return ARTEN.get(art, (art, "gray"))[0]


def art_farbe(art: str) -> str:
    return ARTEN.get(art, (art, "gray"))[1]


def notizname(pfad: str) -> str:
    """``03 Wissen/Docker/Compose.md`` → ``Compose``."""
    return PurePosixPath(pfad).stem


def md_escape(text: str) -> str:
    """Text so maskieren, dass Markdown ihn wörtlich zeigt (Notiztitel sind Nutzertext)."""
    return _MD_SONDERZEICHEN.sub(r"\\\1", text)


def wikilink_chip(name: str, link: str) -> str:
    """``[[Compose]]`` als Markdown-Link, der die Notiz in Obsidian öffnet.

    Der Chip im Wikilink-Stil ist das eine Erkennungsmerkmal des Designs.
    """
    return f"[{md_escape(f'[[{name}]]')}]({link})"


def zeitpunkt(iso: str | None, heute: date | None = None) -> str:
    """ISO-Zeit lesbar in Ortszeit: „heute 03:00“, „gestern 14:20“, „17.11. 09:12“."""
    if not iso:
        return "–"
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if t.tzinfo is not None:
        t = t.astimezone()  # in die Zeitzone des Dashboards (im Container: TZ)
    heute = heute or date.today()
    tage = (heute - t.date()).days
    uhr = f"{t:%H:%M}"
    if tage == 0:
        return f"heute {uhr}"
    if tage == 1:
        return f"gestern {uhr}"
    if tage == -1:
        return f"morgen {uhr}"
    return f"{t:%d.%m.} {uhr}" if t.year == heute.year else f"{t:%d.%m.%Y} {uhr}"


def anzahl(n: int, einzahl: str, mehrzahl: str) -> str:
    """``anzahl(1, "Notiz", "Notizen")`` → „1 Notiz“."""
    return f"{n} {einzahl if n == 1 else mehrzahl}"


def zaehler_text(zaehler: dict[str, int]) -> str:
    """``{"einsortiert": 2, "pruefen": 1}`` → „2 einsortiert, 1 zum Prüfen“."""
    teile: list[str] = []
    for art, wort in [
        ("einsortiert", "einsortiert"),
        ("beantwortet", "beantwortet"),
        ("pruefen", "zum Prüfen"),
        ("fehler", "mit Fehler"),
    ]:
        if zaehler.get(art):
            teile.append(f"{zaehler[art]} {wort}")
    return ", ".join(teile) or "nichts zu tun"
