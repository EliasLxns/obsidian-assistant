"""Indexiert einen Vault: parsen, chunken, nur Geändertes einbetten, Gelöschtes entfernen."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from assistant.index.embedder import Embedder
from assistant.index.store import Fingerprint, VectorStore
from assistant.ingest.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP, Chunk, chunk_note
from assistant.ingest.parser import iter_notes, parse_file


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
    vorhanden = store.fingerprints()
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
