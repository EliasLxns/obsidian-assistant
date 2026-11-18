"""Beobachtet den Vault und indexiert geänderte Notizen nach.

Ablauf: ``watchdog`` meldet jede Dateiänderung → ``VaultEventHandler`` filtert auf Notizen
→ ``ChangeBatcher`` sammelt die Pfade und wartet, bis ``delay`` Sekunden Ruhe ist
→ ``on_flush`` bekommt alle gesammelten Pfade auf einmal (z. B. ``index_notes``).

Warum sammeln? Obsidian speichert beim Tippen alle paar Sekunden, und Sync schreibt
viele Dateien kurz hintereinander. So wird pro Ruhepause nur einmal indexiert.
Schlägt ``on_flush`` fehl (Gaming-PC schläft), bleiben die Pfade vorgemerkt und
werden nach ``retry_delay`` Sekunden erneut versucht.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler, FileSystemMovedEvent
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver
from watchdog.observers.polling import PollingObserver

from assistant.ingest.parser import is_note

log = logging.getLogger(__name__)

FlushFn = Callable[[set[Path]], None]
_RELEVANT = {"created", "modified", "deleted", "moved"}


class ChangeBatcher:
    def __init__(self, on_flush: FlushFn, delay: float = 2.0, retry_delay: float = 60.0) -> None:
        self.on_flush = on_flush
        self.delay = delay
        self.retry_delay = retry_delay
        self._offen: set[Path] = set()
        self._sperre = threading.Lock()
        self._timer: threading.Timer | None = None

    @property
    def pending(self) -> set[Path]:
        with self._sperre:
            return set(self._offen)

    def add(self, path: Path) -> None:
        with self._sperre:
            self._offen.add(path)
            self._starte_timer(self.delay)

    def _starte_timer(self, sekunden: float) -> None:
        # Nur unter self._sperre aufrufen.
        if self._timer is not None:
            self._timer.cancel()
        self._timer = threading.Timer(sekunden, self.flush)
        self._timer.daemon = True
        self._timer.start()

    def flush(self) -> None:
        """Übergibt alle gesammelten Pfade an ``on_flush``. Bei Fehlern bleiben sie vorgemerkt."""
        with self._sperre:
            pfade, self._offen = self._offen, set()
            self._timer = None
        if not pfade:
            return
        try:
            self.on_flush(pfade)
        except Exception:
            log.exception("Indexieren fehlgeschlagen, neuer Versuch in %.0f s", self.retry_delay)
            with self._sperre:
                self._offen |= pfade
                if self._timer is None:  # neue Änderungen haben schon einen Timer gestartet
                    self._starte_timer(self.retry_delay)

    def stop(self) -> None:
        with self._sperre:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


class VaultEventHandler(FileSystemEventHandler):
    """Leitet Änderungen an Notizen an den ``ChangeBatcher`` weiter, alles andere nicht."""

    def __init__(self, vault: Path, batcher: ChangeBatcher) -> None:
        self.vault = vault.resolve()
        self.batcher = batcher

    def _melden(self, roh: str | bytes) -> None:
        pfad = Path(roh.decode() if isinstance(roh, bytes) else roh).resolve()
        if is_note(pfad, self.vault):
            self.batcher.add(pfad)

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in _RELEVANT:
            return
        self._melden(event.src_path)
        if isinstance(event, FileSystemMovedEvent):
            self._melden(event.dest_path)  # Umbenennen = alte Notiz weg, neue da


def watch_vault(
    vault: Path, batcher: ChangeBatcher, *, polling: bool = False, poll_interval: float = 10.0
) -> BaseObserver:
    """Startet die Beobachtung im Hintergrund. Beenden mit ``observer.stop()``.

    ``polling=True`` fragt das Dateisystem regelmäßig ab, statt auf Meldungen des
    Betriebssystems zu warten. Nötig, wenn der Vault per Docker Desktop von Windows
    eingebunden ist; dort kommen keine inotify-Meldungen im Container an.
    ``poll_interval`` ist bewusst groß: Der Gaming-PC soll beim Spielen nicht belastet werden.
    """
    observer: BaseObserver = PollingObserver(timeout=poll_interval) if polling else Observer()
    observer.schedule(VaultEventHandler(vault, batcher), str(vault), recursive=True)
    observer.start()
    return observer
