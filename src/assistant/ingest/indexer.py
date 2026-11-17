"""Indexiert einen Vault: parsen, chunken, nur Geändertes einbetten, Gelöschtes entfernen.

Zwei Wege mit demselben Hash-Vergleich (Fingerabdruck aus Chunk-Hash und Modell):

- ``index_vault``: der ganze Vault, beim Start und für ``/reindex``
- ``index_notes``: nur die Dateien, die der Watcher als geändert meldet
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from assistant.index.embedder import Embedder
from assistant.index.store import Fingerprint, VectorStore
from assistant.ingest.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, Chunk, chunk_note
from assistant.ingest.parser import is_note, iter_notes, parse_file


@dataclass(frozen=True)
class IndexReport:
    notes: int
    chunks: int
    embedded: int  # neu oder geändert, wurden eingebettet
    unchanged: int
    deleted: int


def collect_chunks(
    vault: Path, max_chars: int = DEFAULT_MAX_CHARS, overlap: int = DEFAULT_OVERLAP
) -> tuple[int, list[Chunk]]:
    """Liest alle Notizen und gibt (Anzahl Notizen, Chunks) zurück."""
    if not vault.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {vault}")
    dateien = iter_notes(vault)
    chunks: list[Chunk] = []
    for datei in dateien:
        chunks.extend(chunk_note(parse_file(datei, vault), max_chars, overlap))
    return len(dateien), chunks


def index_vault(
    vault: Path,
    embedder: Embedder,
    store: VectorStore,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
    batch_size: int = 64,
) -> IndexReport:
    anzahl_notizen, chunks = collect_chunks(vault, max_chars, overlap)
    return _abgleichen(chunks, store.fingerprints(), anzahl_notizen, embedder, store, batch_size)


def path_of(chunk_id: str) -> str:
    """Notiz-Pfad aus einer Chunk-ID ``"<pfad>#<nr>"``."""
    return chunk_id.rsplit("#", 1)[0]


def index_notes(
    vault: Path,
    paths: Iterable[Path],
    embedder: Embedder,
    store: VectorStore,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap: int = DEFAULT_OVERLAP,
    batch_size: int = 64,
) -> IndexReport:
    """Indexiert nur einzelne Notizen neu. Eine Datei, die nicht mehr existiert, wird entfernt.

    Verglichen wird nur mit den Chunks dieser Notizen, der Rest des Index bleibt unberührt.
    """
    vault = vault.resolve()
    absolut = [p.resolve() for p in paths]
    rel = {p.relative_to(vault).as_posix(): p for p in absolut if is_note(p, vault)}
    chunks: list[Chunk] = []
    notizen = 0
    for datei in rel.values():
        if datei.is_file():
            notizen += 1
            chunks.extend(chunk_note(parse_file(datei, vault), max_chars, overlap))
    vorhanden = {i: f for i, f in store.fingerprints().items() if path_of(i) in rel}
    return _abgleichen(chunks, vorhanden, notizen, embedder, store, batch_size)


def _abgleichen(
    chunks: list[Chunk],
    vorhanden: dict[str, Fingerprint],
    anzahl_notizen: int,
    embedder: Embedder,
    store: VectorStore,
    batch_size: int,
) -> IndexReport:
    """Bettet neue/geänderte Chunks ein und löscht die, die es nicht mehr gibt.

    ``vorhanden`` sind die Fingerabdrücke im Index, die zu den ``chunks`` gehören sollen.
    """
    modell = embedder.model_name
    neu = [c for c in chunks if vorhanden.get(c.id) != Fingerprint(c.hash, modell)]
    for start in range(0, len(neu), batch_size):
        batch = neu[start : start + batch_size]
        vektoren = embedder.embed_documents([c.embed_text for c in batch])
        store.upsert(batch, vektoren, modell)

    aktuelle_ids = {c.id for c in chunks}
    veraltet = [i for i in vorhanden if i not in aktuelle_ids]
    store.delete(veraltet)

    return IndexReport(
        notes=anzahl_notizen,
        chunks=len(chunks),
        embedded=len(neu),
        unchanged=len(chunks) - len(neu),
        deleted=len(veraltet),
    )
