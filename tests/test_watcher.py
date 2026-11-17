"""Watcher-Tests: Sammeln mit kurzer Wartezeit und einmal mit echtem watchdog-Observer."""

import shutil
import threading
import time
from pathlib import Path

import pytest
from watchdog.events import DirModifiedEvent, FileModifiedEvent, FileMovedEvent

from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.ingest.indexer import index_notes, index_vault, path_of
from assistant.ingest.watcher import ChangeBatcher, VaultEventHandler, watch_vault
from tests.conftest import DEMO_VAULT


def _warte_bis(bedingung: threading.Event, sekunden: float = 5.0) -> bool:
    return bedingung.wait(sekunden)


class Sammler:
    def __init__(self, fehler: int = 0) -> None:
        self.aufrufe: list[set[Path]] = []
        self.fehler = fehler
        self.fertig = threading.Event()

    def __call__(self, pfade: set[Path]) -> None:
        if self.fehler:
            self.fehler -= 1
            raise RuntimeError("Gaming-PC schläft")
        self.aufrufe.append(pfade)
        self.fertig.set()


def test_batcher_fasst_aenderungen_zusammen() -> None:
    sammler = Sammler()
    b = ChangeBatcher(sammler, delay=0.1)
    for name in ["a.md", "b.md", "a.md"]:
        b.add(Path(name))
    assert _warte_bis(sammler.fertig)
    time.sleep(0.2)
    assert sammler.aufrufe == [{Path("a.md"), Path("b.md")}]
    assert b.pending == set()


def test_batcher_versucht_es_nach_fehler_erneut() -> None:
    sammler = Sammler(fehler=1)
    b = ChangeBatcher(sammler, delay=0.05, retry_delay=0.1)
    b.add(Path("a.md"))
    assert _warte_bis(sammler.fertig)
    assert sammler.aufrufe == [{Path("a.md")}]


def test_batcher_stop_verwirft_timer() -> None:
    sammler = Sammler()
    b = ChangeBatcher(sammler, delay=0.1)
    b.add(Path("a.md"))
    b.stop()
    time.sleep(0.2)
    assert sammler.aufrufe == []
    assert b.pending == {Path("a.md")}


def test_handler_filtert_auf_notizen(tmp_path: Path) -> None:
    sammler = Sammler()
    b = ChangeBatcher(sammler, delay=60)
    h = VaultEventHandler(tmp_path, b)
    h.dispatch(FileModifiedEvent(str(tmp_path / "Notiz.md")))
    h.dispatch(FileModifiedEvent(str(tmp_path / "Bild.png")))
    h.dispatch(FileModifiedEvent(str(tmp_path / ".obsidian/workspace.md")))
    h.dispatch(DirModifiedEvent(str(tmp_path / "Ordner")))
    h.dispatch(FileMovedEvent(str(tmp_path / "Alt.md"), str(tmp_path / "Neu.md")))
    b.stop()
    root = tmp_path.resolve()
    assert b.pending == {root / "Notiz.md", root / "Alt.md", root / "Neu.md"}


@pytest.mark.parametrize("polling", [False, True])
def test_watcher_indexiert_neue_notiz(tmp_path: Path, polling: bool) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    embedder, store = FakeEmbedder(), InMemoryStore()
    index_vault(vault, embedder, store)

    fertig = threading.Event()

    def nachindexieren(pfade: set[Path]) -> None:
        index_notes(vault, pfade, embedder, store)
        if any(path_of(i) == "00 Inbox/Watcher.md" for i in store.fingerprints()):
            fertig.set()

    batcher = ChangeBatcher(nachindexieren, delay=0.1)
    observer = watch_vault(vault, batcher, polling=polling)
    try:
        (vault / "00 Inbox/Watcher.md").write_text("# Watcher\n\nHallo.\n", encoding="utf-8")
        assert _warte_bis(fertig), "Watcher hat die neue Notiz nicht indexiert"
    finally:
        observer.stop()
        observer.join(timeout=5)
        batcher.stop()
