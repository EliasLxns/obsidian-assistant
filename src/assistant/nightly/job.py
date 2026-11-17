"""Der Nachtlauf: Gaming-PC wecken, sichern, Fragen beantworten, Inbox sortieren, protokollieren.

1. Ollama erreichbar? Sonst Wake-on-LAN und warten (Abbruch nach ``WOL_WAIT_S``).
2. Git-Commit des Vaults („Stand vor Lauf …“).
3. Index abgleichen, damit auch Notizen von gestern gefunden werden.
4. „Frage:“-Notizen beantworten, alle anderen Inbox-Notizen einsortieren.
5. Protokoll-Notiz schreiben, zweiter Git-Commit, Lauf als JSON für Rückgängig speichern.
6. Modelle aus dem VRAM entladen.

Im Probelauf (``--probelauf``) wird alles berechnet, aber nichts geschrieben.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from assistant.components import Components
from assistant.index.embedder import OllamaError
from assistant.ingest.indexer import index_vault
from assistant.ingest.parser import Note, parse_markdown
from assistant.nightly import inbox, protocol, questions
from assistant.nightly.inbox import PROTOKOLL, PRUEFEN
from assistant.nightly.protocol import Aktion, Lauf, schreiben, text_hash
from assistant.nightly.vault_git import GitError, VaultGit
from assistant.nightly.wol import Waker, wake_and_wait
from assistant.retrieval.search import Retriever


@dataclass(frozen=True)
class Optionen:
    probelauf: bool = False
    min_alter: timedelta = timedelta(minutes=30)
    min_score: float = 0.3  # verwandte Notizen erst ab diesem Score verlinken
    git: bool = True
    schon_wach_ueberspringen: bool = False  # Gaming-Schutz, siehe guard.py


def _freier_pfad(ziel: Path) -> Path:
    """``Notiz.md`` → ``Notiz (2).md``, falls es den Namen schon gibt."""
    nr = 2
    kandidat = ziel
    while kandidat.exists():
        kandidat = ziel.with_name(f"{ziel.stem} ({nr}){ziel.suffix}")
        nr += 1
    return kandidat


def run_nightly(
    c: Components,
    vault: Path,
    *,
    jetzt: datetime,
    is_awake: Callable[[], bool],
    waker: Waker | None,
    optionen: Optionen | None = None,
    wol_timeout_s: float = 180.0,
    entladen: Callable[[], None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Lauf:
    s = c.settings
    lauf = Lauf(id=jetzt.strftime("%Y-%m-%d_%H%M%S"), start=jetzt.isoformat(timespec="seconds"))
    optionen = optionen or Optionen()
    lauf.probelauf = optionen.probelauf
    try:
        _ablauf(c, vault, lauf, jetzt, is_awake, waker, optionen, wol_timeout_s, sleep)
    finally:
        lauf.ende = datetime.now().isoformat(timespec="seconds")
        protocol.speichern(s.nightly_state_path, lauf)
        if entladen is not None:
            entladen()
    return lauf


def _ablauf(
    c: Components,
    vault: Path,
    lauf: Lauf,
    jetzt: datetime,
    is_awake: Callable[[], bool],
    waker: Waker | None,
    optionen: Optionen,
    wol_timeout_s: float,
    sleep: Callable[[float], None],
) -> None:
    s = c.settings
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {vault}")

    # 1. Gaming-PC
    pc = wake_and_wait(is_awake, waker, timeout_s=wol_timeout_s, sleep=sleep)
    if pc.war_wach:
        lauf.pc = "war schon wach"
        if optionen.schon_wach_ueberspringen:
            lauf.hinweise.append("Übersprungen: Der PC lief schon, vielleicht wird gespielt.")
            return
    elif pc.erreichbar:
        lauf.pc = f"geweckt nach {pc.wartezeit_s:.0f} s"
    else:
        lauf.pc = "nicht erreichbar" if waker else "nicht erreichbar, keine MAC konfiguriert"
        lauf.hinweise.append("Abgebrochen: Ollama antwortet nicht. Nächster Versuch morgen.")
        return

    # 2. Sicherung
    git = VaultGit(vault) if optionen.git and not optionen.probelauf else None
    if git is not None:
        try:
            if git.einrichten():
                lauf.hinweise.append("Git-Repo im Vault neu angelegt.")
            lauf.git_vorher = git.commit(f"Nachtjob: Stand vor Lauf {lauf.id}")
        except GitError as e:
            lauf.hinweise.append(f"Abgebrochen: Git-Sicherung fehlgeschlagen ({e}).")
            return

    # 3. Index
    index_vault(vault, c.embedder, c.store)
    retriever = Retriever(c.embedder, c.store)
    ordner = inbox.zielordner(vault, s.inbox_dir)
    namen = inbox.wikilink_namen(vault)

    # 4. Inbox
    for datei in inbox.inbox_notes(vault, s.inbox_dir, jetzt, optionen.min_alter):
        rel = datei.relative_to(vault).as_posix()
        text = datei.read_text(encoding="utf-8")
        note = parse_markdown(text, rel)
        try:
            if inbox.ist_frage(note):
                ergebnis = _frage(note, text, rel, retriever, c, namen, jetzt, s.inbox_dir)
            else:
                ergebnis = _sortieren(note, text, rel, vault, retriever, c, ordner, namen, optionen)
        except OllamaError as e:
            lauf.aktionen.append(Aktion("fehler", rel, details=str(e)))
            lauf.hinweise.append("Abgebrochen: Ollama ist während des Laufs ausgefallen.")
            break
        if ergebnis is None:
            continue
        aktion, neu = ergebnis
        aktion.neu_hash = text_hash(neu)
        if not optionen.probelauf:
            ziel = vault / aktion.ziel
            schreiben(ziel, neu)  # erst schreiben, dann das Original löschen
            if ziel != datei:
                datei.unlink()
        lauf.aktionen.append(aktion)

    # 5. Protokoll und zweiter Commit
    if optionen.probelauf:
        return
    lauf.ende = datetime.now().isoformat(timespec="seconds")
    md = vault / s.inbox_dir / PROTOKOLL / f"Nachtjob {lauf.id}.md"
    schreiben(md, protocol.als_markdown(lauf))
    if git is not None:
        try:
            lauf.git_nachher = git.commit(f"Nachtjob: Lauf {lauf.id}")
        except GitError as e:
            lauf.hinweise.append(f"Git-Commit nach dem Lauf fehlgeschlagen ({e}).")


def _frage(
    note: Note,
    text: str,
    rel: str,
    retriever: Retriever,
    c: Components,
    namen: Counter[str],
    jetzt: datetime,
    inbox_dir: str,
) -> tuple[Aktion, str] | None:
    ergebnis = questions.beantworte(
        note, text, retriever, c.llm, namen, jetzt.date(), inbox_dir=inbox_dir
    )
    if ergebnis is None:
        return None
    neu, quellen = ergebnis
    return Aktion("beantwortet", rel, rel, f"{quellen} Quellen", original=text), neu


def _sortieren(
    note: Note,
    text: str,
    rel: str,
    vault: Path,
    retriever: Retriever,
    c: Components,
    ordner: dict[str, list[str]],
    namen: Counter[str],
    optionen: Optionen,
) -> tuple[Aktion, str]:
    s = c.settings
    verwandt = inbox.verwandte_notizen(retriever, text, s.inbox_dir, min_score=optionen.min_score)
    e = inbox.entscheiden(note, text, ordner, verwandt, c.llm)
    links = [inbox.wikilink(h.chunk.path, namen) for h in verwandt]
    neu = inbox.notiz_ergaenzen(text, e.tags, links)

    dateiname = Path(rel).name
    if e.sicher and e.ordner and not (vault / e.ordner / dateiname).exists():
        art, ziel = "einsortiert", vault / e.ordner / dateiname
    else:
        art = "pruefen"
        ziel = _freier_pfad(vault / s.inbox_dir / PRUEFEN / dateiname)
        if e.sicher and e.ordner:
            e = inbox.Entscheidung(e.ordner, e.tags, False, f"{dateiname} gibt es dort schon")
    teile = [f"Tags: {', '.join(e.tags) or '–'}", f"Links: {len(links)}"]
    if art == "pruefen":
        vorschlag = f"Vorschlag {e.ordner}. " if e.ordner else ""
        teile.append(f"{vorschlag}{e.grund}".strip())
    aktion = Aktion(art, rel, ziel.relative_to(vault).as_posix(), "; ".join(teile), original=text)
    return aktion, neu
