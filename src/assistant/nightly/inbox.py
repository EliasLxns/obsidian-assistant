"""Inbox-Sortierer: neue Notizen verschlagworten, verlinken und einsortieren.

Ablauf je Notiz in ``00 Inbox`` (nur die oberste Ebene, Unterordner wie ``Prüfen`` bleiben):

1. Verwandte Notizen über die Suche finden (nicht aus der Inbox).
2. Das Chat-Modell wählt als JSON einen **vorhandenen** Ordner und 1–5 Tags
   und sagt, ob es sich sicher ist.
3. Tags kommen ins Frontmatter, die verwandten Notizen als Wikilinks unter ``## Verwandt``.
4. Sicher und Ordner gültig → dorthin verschieben. Sonst → ``00 Inbox/Prüfen``.

Die KI erfindet keine Ordner und fasst keine bestehenden Notizen an: Geändert wird nur
die neue Notiz selbst, bevor sie die Inbox verlässt.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, cast

from assistant.index.store import Hit
from assistant.ingest.parser import (
    Note,
    frontmatter_tags,
    iter_notes,
    parse_markdown,
    split_frontmatter,
)
from assistant.llm.client import LLM
from assistant.retrieval.search import Retriever

PRUEFEN = "Prüfen"
PROTOKOLL = "Protokoll"
MAX_TAGS = 5
MAX_ZEICHEN_IM_PROMPT = 3000
_TAG_ERLAUBT = re.compile(r"[^\w/-]+")


@dataclass(frozen=True)
class Entscheidung:
    ordner: str | None  # relativ zum Vault, None: unklar
    tags: tuple[str, ...]
    sicher: bool
    grund: str


def inbox_notes(
    vault: Path, inbox_dir: str, jetzt: datetime, min_alter: timedelta = timedelta(minutes=30)
) -> list[Path]:
    """Markdown-Dateien direkt in der Inbox, die länger als ``min_alter`` nicht geändert wurden.

    Frisch bearbeitete Notizen bleiben liegen: Vielleicht schreibt gerade jemand daran.
    """
    inbox = vault / inbox_dir
    if not inbox.is_dir():
        return []
    grenze = (jetzt - min_alter).timestamp()
    return sorted(
        p
        for p in inbox.glob("*.md")
        if p.is_file() and not p.name.startswith(".") and p.stat().st_mtime <= grenze
    )


def ist_frage(note: Note) -> bool:
    """„Frage:“-Notizen: Titel beginnt mit „Frage:“ oder Tag ``frage``."""
    return note.title.lower().startswith("frage:") or "frage" in {t.lower() for t in note.tags}


def zielordner(
    vault: Path, inbox_dir: str, beispiele: int = 4, dateien: Sequence[Path] | None = None
) -> dict[str, list[str]]:
    """Ordner mit Notizen außerhalb der Inbox → einige Notiztitel als Beispiel fürs Modell."""
    ordner: dict[str, list[str]] = {}
    for datei in iter_notes(vault) if dateien is None else dateien:
        rel = datei.relative_to(vault)
        if len(rel.parts) < 2 or rel.parts[0] == inbox_dir:
            continue
        liste = ordner.setdefault(rel.parent.as_posix(), [])
        if len(liste) < beispiele:
            liste.append(datei.stem)
    return dict(sorted(ordner.items()))


def wikilink_namen(vault: Path, dateien: Sequence[Path] | None = None) -> Counter[str]:
    """Wie oft jeder Notizname vorkommt. Eindeutige Namen reichen als Wikilink."""
    return Counter(p.stem for p in (iter_notes(vault) if dateien is None else dateien))


def wikilink(pfad: str, namen: Counter[str]) -> str:
    """``[[Compose]]``, bei doppelten Namen ``[[03 Wissen/Docker/Compose]]``."""
    ohne_endung = pfad.removesuffix(".md")
    name = Path(ohne_endung).name
    return f"[[{name}]]" if namen[name] <= 1 else f"[[{ohne_endung}]]"


def verwandte_notizen(
    retriever: Retriever,
    text: str,
    inbox_dir: str,
    *,
    k: int = 3,
    min_score: float = 0.5,
    max_abstand: float = 0.1,
) -> list[Hit]:
    """Die ``k`` ähnlichsten Notizen außerhalb der Inbox.

    Zwei Schwellen verhindern Links „ins Blaue“: Score ≥ ``min_score`` (Kosinus, die Suche
    muss im Modus ``vektor`` laufen) und höchstens ``max_abstand`` hinter dem besten Treffer.
    Die Werte stammen aus dem Probelauf mit bge-m3 und werden mit echten Notizen nachjustiert.
    """
    treffer = retriever.search_notes(text[:MAX_ZEICHEN_IM_PROMPT], k * 3)
    kandidaten = [h for h in treffer if not h.chunk.path.startswith(f"{inbox_dir}/")]
    if not kandidaten:
        return []
    bester = kandidaten[0].score
    passend = [h for h in kandidaten if h.score >= min_score and bester - h.score <= max_abstand]
    return passend[:k]


def vorhandene_tags(
    vault: Path, inbox_dir: str, dateien: Sequence[Path] | None = None, maximal: int = 60
) -> list[str]:
    """Die häufigsten Tags außerhalb der Inbox, damit das Modell sie wiederverwendet."""
    zaehler: Counter[str] = Counter()
    for datei in iter_notes(vault) if dateien is None else dateien:
        rel = datei.relative_to(vault)
        if rel.parts[0] == inbox_dir:
            continue
        try:
            note = parse_markdown(
                datei.read_text(encoding="utf-8", errors="replace"), rel.as_posix()
            )
        except OSError:
            continue
        zaehler.update(t.lower() for t in note.tags)
    return [t for t, _ in zaehler.most_common(maximal)]


SORT_SYSTEM = """Du sortierst neue Notizen in einen Obsidian-Vault ein.
Antworte nur mit einem JSON-Objekt:
{"ordner": "<einer der vorgegebenen Ordner oder null>", "tags": ["..."], "sicher": true|false,
 "grund": "<ein kurzer Satz auf Deutsch>"}
Regeln:
- Wähle genau einen Ordner aus der Liste. Erfinde keine Ordner.
- 1 bis 5 Tags, kleingeschrieben, ohne #, ohne Leerzeichen (Bindestrich statt Leerzeichen).
- Nimm vorhandene Tags aus der Liste, wenn sie passen. Neue Tags nur, wenn keiner passt.
- Schreibe Umlaute als ä, ö, ü und ß (also "bewässerung", nicht "bewaesserung").
- "sicher" nur, wenn die Notiz eindeutig zu dem Ordner passt. Sonst false."""


def build_sort_prompt(
    note: Note,
    text: str,
    ordner: dict[str, list[str]],
    verwandt: Sequence[Hit],
    tags: Sequence[str] = (),
) -> str:
    zeilen = ["Ordner (mit Beispielnotizen):"]
    for name, beispiele in ordner.items():
        zeilen.append(f"- {name}: {', '.join(beispiele)}")
    if tags:
        zeilen += ["", f"Vorhandene Tags: {', '.join(tags)}"]
    if verwandt:
        zeilen += ["", "Ähnliche vorhandene Notizen:"]
        zeilen += [f"- {h.chunk.path}" for h in verwandt]
    _, body = split_frontmatter(text)
    zeilen += ["", f"Neue Notiz „{note.title}“:", body[:MAX_ZEICHEN_IM_PROMPT].strip(), "", "JSON:"]
    return "\n".join(zeilen)


def _tag(roh: str) -> str:
    return _TAG_ERLAUBT.sub("-", roh.strip().lstrip("#").lower()).strip("-")


def parse_entscheidung(roh: str, ordner: Sequence[str]) -> Entscheidung:
    """Liest die JSON-Antwort des Modells. Alles Unklare wird zu „nicht sicher“."""
    try:
        start, ende = roh.index("{"), roh.rindex("}") + 1
        daten = json.loads(roh[start:ende])
    except ValueError:
        return Entscheidung(None, (), False, "Antwort des Modells war kein JSON")
    if not isinstance(daten, dict):
        return Entscheidung(None, (), False, "Antwort des Modells war kein JSON-Objekt")
    d = cast(dict[str, Any], daten)

    tags_roh: object = d.get("tags") or []
    tag_liste = cast(list[object], tags_roh) if isinstance(tags_roh, list) else []
    tags = tuple(dict.fromkeys(t for t in (_tag(str(x)) for x in tag_liste) if t))[:MAX_TAGS]
    grund = str(d.get("grund") or "").strip()

    gewaehlt = d.get("ordner")
    if not isinstance(gewaehlt, str) or gewaehlt.strip().strip("/") not in ordner:
        hinweis = f"Ordner {gewaehlt!r} gibt es nicht" if gewaehlt else "kein Ordner gewählt"
        return Entscheidung(None, tags, False, f"{hinweis}. {grund}".strip())
    return Entscheidung(gewaehlt.strip().strip("/"), tags, d.get("sicher") is True, grund)


def entscheiden(
    note: Note,
    text: str,
    ordner: dict[str, list[str]],
    verwandt: Sequence[Hit],
    llm: LLM,
    tags: Sequence[str] = (),
) -> Entscheidung:
    if not ordner:
        return Entscheidung(None, (), False, "Im Vault gibt es noch keine Zielordner")
    prompt = build_sort_prompt(note, text, ordner, verwandt, tags)
    roh = llm.generate(prompt, system=SORT_SYSTEM, json=True)
    return parse_entscheidung(roh, list(ordner))


def _tags_zeile_ersetzen(kopf: str, tags: Sequence[str]) -> str:
    """Ersetzt nur den ``tags:``-Eintrag im rohen Frontmatter, alle anderen Zeilen bleiben
    Zeichen für Zeichen gleich (Kommentare, Datumsformate, Anführungszeichen)."""
    zeilen = kopf.split("\n")
    neu_zeile = f"tags: [{', '.join(tags)}]"
    for i, zeile in enumerate(zeilen):
        if re.match(r"^tags?\s*:", zeile):
            ende = i + 1
            # Block-Liste darunter (``- a``) gehört mit dazu
            while ende < len(zeilen) and re.match(r"^\s*-\s", zeilen[ende]):
                ende += 1
            return "\n".join([*zeilen[:i], neu_zeile, *zeilen[ende:]])
    return "\n".join([*zeilen, neu_zeile]) if kopf else neu_zeile


def notiz_ergaenzen(text: str, tags: Sequence[str], links: Sequence[str]) -> str:
    """Tags ins Frontmatter, Links unter ``## Verwandt``. Bestehendes bleibt erhalten.

    Ist das Frontmatter kein gültiges YAML, bleibt es unangetastet und es kommen keine Tags
    dazu: Lieber ohne Tags einsortieren als Eigenschaften der Notiz zerstören.
    """
    text = text.replace("\r\n", "\n")
    frontmatter, body = split_frontmatter(text)
    kopf_roh = text[: len(text) - len(body)]  # "---\n…\n---\n" oder ""
    neue_links = [link for link in links if link not in body]
    if neue_links:
        body = body.rstrip("\n") + "\n\n## Verwandt\n\n" + "".join(f"- {x}\n" for x in neue_links)

    vorhanden = frontmatter_tags(frontmatter)
    alle_tags = list(dict.fromkeys([*vorhanden, *tags]))
    ungueltig = bool(kopf_roh) and not frontmatter and kopf_roh.strip() != "---\n---".strip()
    if ungueltig or alle_tags == vorhanden:
        return kopf_roh + body
    if not kopf_roh:
        return f"---\n{_tags_zeile_ersetzen('', alle_tags)}\n---\n{body}"
    innen = re.sub(r"\n?---\n?$", "", kopf_roh[4:])
    return f"---\n{_tags_zeile_ersetzen(innen, alle_tags)}\n---\n{body}"
