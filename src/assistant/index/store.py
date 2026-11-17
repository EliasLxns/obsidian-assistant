"""VectorStore: speichert Chunks mit Vektoren und Metadaten und findet die ähnlichsten.

``VectorStore`` ist das Interface. ``ChromaStore`` nutzt ChromaDB,
``InMemoryStore`` hält alles im Speicher (Tests und Eval-Läufe).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

from assistant.ingest.chunker import Chunk


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float  # Kosinus-Ähnlichkeit, höher ist besser


@dataclass(frozen=True)
class Fingerprint:
    """Was im Index zu einem Chunk liegt. Ändert sich Hash oder Modell, wird neu eingebettet."""

    hash: str
    model: str


class VectorStore(Protocol):
    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]], model: str
    ) -> None: ...

    def query(self, vector: Sequence[float], k: int) -> list[Hit]: ...

    def fingerprints(self) -> dict[str, Fingerprint]:
        """Chunk-ID → Fingerabdruck aller gespeicherten Chunks."""
        ...

    def delete(self, ids: Sequence[str]) -> None: ...

    def count(self) -> int: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    zaehler = sum(x * y for x, y in zip(a, b, strict=True))
    nenner = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return zaehler / nenner if nenner else 0.0


class InMemoryStore:
    def __init__(self) -> None:
        self._daten: dict[str, tuple[Chunk, list[float], str]] = {}

    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]], model: str
    ) -> None:
        for chunk, vec in zip(chunks, vectors, strict=True):
            self._daten[chunk.id] = (chunk, list(vec), model)

    def query(self, vector: Sequence[float], k: int) -> list[Hit]:
        hits = [Hit(c, cosine(vector, v)) for c, v, _ in self._daten.values()]
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def fingerprints(self) -> dict[str, Fingerprint]:
        return {i: Fingerprint(c.hash, m) for i, (c, _, m) in self._daten.items()}

    def delete(self, ids: Sequence[str]) -> None:
        for i in ids:
            self._daten.pop(i, None)

    def count(self) -> int:
        return len(self._daten)


_TRENNER = "\x1f"  # Chroma-Metadaten erlauben nur Skalare, Listen werden zu einem String


def _join(werte: Sequence[str]) -> str:
    return _TRENNER.join(werte)


def _split(wert: object) -> tuple[str, ...]:
    return tuple(t for t in str(wert or "").split(_TRENNER) if t)


class ChromaStore:
    """ChromaDB-Collection mit Kosinus-Distanz.

    Metadaten je Chunk: ``path``, ``title``, ``heading``, ``tags``, ``links``, ``hash``, ``model``.
    Lokal (``path``) für die Entwicklung, per HTTP (``host``/``port``) im Docker-Betrieb.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        host: str | None = None,
        port: int = 8000,
        collection: str = "vault",
    ) -> None:
        import chromadb  # erst hier, damit Tests mit InMemoryStore Chroma nicht laden müssen

        if host:
            client: Any = chromadb.HttpClient(host=host, port=port)
        else:
            client = chromadb.PersistentClient(path=str(path or Path(".chroma")))
        self._client = client
        self._col: Any = client.get_or_create_collection(
            name=collection, metadata={"hnsw:space": "cosine"}
        )

    def upsert(
        self, chunks: Sequence[Chunk], vectors: Sequence[Sequence[float]], model: str
    ) -> None:
        if not chunks:
            return
        self._col.upsert(
            ids=[c.id for c in chunks],
            embeddings=[list(v) for v in vectors],
            documents=[c.text for c in chunks],
            metadatas=[
                {
                    "path": c.path,
                    "title": c.title,
                    "heading": c.heading,
                    "tags": _join(c.tags),
                    "links": _join(c.links),
                    "hash": c.hash,
                    "model": model,
                }
                for c in chunks
            ],
        )

    @staticmethod
    def _chunk(chunk_id: str, text: str, meta: dict[str, Any]) -> Chunk:
        return Chunk(
            id=chunk_id,
            path=str(meta.get("path", "")),
            title=str(meta.get("title", "")),
            heading=str(meta.get("heading", "")),
            text=text,
            tags=_split(meta.get("tags")),
            links=_split(meta.get("links")),
        )

    def query(self, vector: Sequence[float], k: int) -> list[Hit]:
        anzahl = self.count()
        if anzahl == 0:
            return []
        res = cast(
            dict[str, Any],
            self._col.query(
                query_embeddings=[list(vector)],
                n_results=min(k, anzahl),
                include=["documents", "metadatas", "distances"],
            ),
        )
        ids = cast(list[str], res["ids"][0])
        docs = cast(list[str], res["documents"][0])
        metas = cast(list[dict[str, Any]], res["metadatas"][0])
        dists = cast(list[float], res["distances"][0])
        return [
            Hit(self._chunk(i, d, m), 1.0 - dist)
            for i, d, m, dist in zip(ids, docs, metas, dists, strict=True)
        ]

    def fingerprints(self) -> dict[str, Fingerprint]:
        res = cast(dict[str, Any], self._col.get(include=["metadatas"]))
        ids = cast(list[str], res["ids"])
        metas = cast(list[dict[str, Any]], res["metadatas"])
        return {
            i: Fingerprint(str(m.get("hash", "")), str(m.get("model", "")))
            for i, m in zip(ids, metas, strict=True)
        }

    def delete(self, ids: Sequence[str]) -> None:
        if ids:
            self._col.delete(ids=list(ids))

    def count(self) -> int:
        return int(self._col.count())
