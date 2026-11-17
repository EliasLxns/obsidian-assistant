"""Embedder: wandelt Texte in Vektoren um.

``Embedder`` ist das Interface. ``OllamaEmbedder`` spricht mit Ollama,
``FakeEmbedder`` rechnet deterministisch ohne Netzwerk und ist für Tests gedacht.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast

import httpx

Vector = list[float]


class Embedder(Protocol):
    @property
    def model_name(self) -> str: ...

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        """Vektoren für Chunks, die in den Index kommen."""
        ...

    def embed_query(self, text: str) -> Vector:
        """Vektor für eine Suchanfrage."""
        ...


def _normalize(vec: Sequence[float]) -> Vector:
    laenge = math.sqrt(sum(x * x for x in vec))
    return [x / laenge for x in vec] if laenge else list(vec)


class FakeEmbedder:
    """Bag-of-Words-Vektoren über Hashing: gleiche Wörter ergeben ähnliche Vektoren.

    Das reicht, damit Tests echte Suchergebnisse prüfen können, ohne Ollama.
    Zusätzlich zu ganzen Wörtern fließen Wortanfänge (6 Zeichen) ein, damit
    „Container“ und „Containern“ zueinander passen.
    """

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.calls = 0  # Anzahl eingebetteter Texte, damit Tests den Cache prüfen können

    @property
    def model_name(self) -> str:
        return f"fake-{self.dim}"

    def _vector(self, text: str) -> Vector:
        vec = [0.0] * self.dim
        for wort in re.findall(r"\w+", text.lower()):
            for merkmal in {wort, wort[:6]}:
                h = int.from_bytes(hashlib.blake2b(merkmal.encode(), digest_size=8).digest())
                vec[h % self.dim] += 1.0
        return _normalize(vec)

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        self.calls += len(texts)
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> Vector:
        self.calls += 1
        return self._vector(text)


class EmbeddingCache:
    """SQLite-Cache: Hash aus Modell und Text → Vektor.

    Beim Neuindexieren und bei jedem Eval-Lauf werden so nur geänderte Texte
    wirklich an Ollama geschickt.
    """

    def __init__(self, path: Path | str = ":memory:") -> None:
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.execute("CREATE TABLE IF NOT EXISTS emb (key TEXT PRIMARY KEY, vec TEXT NOT NULL)")

    @staticmethod
    def key(model: str, text: str) -> str:
        return hashlib.sha256(f"{model}\0{text}".encode()).hexdigest()

    def get_many(self, keys: Sequence[str]) -> dict[str, Vector]:
        gefunden: dict[str, Vector] = {}
        for start in range(0, len(keys), 500):  # SQLite-Limit für Platzhalter
            teil = list(keys[start : start + 500])
            platzhalter = ",".join("?" * len(teil))
            zeilen = self._db.execute(
                f"SELECT key, vec FROM emb WHERE key IN ({platzhalter})", teil
            ).fetchall()
            for key, vec in cast(list[tuple[str, str]], zeilen):
                gefunden[key] = cast(Vector, json.loads(vec))
        return gefunden

    def put_many(self, items: dict[str, Vector]) -> None:
        with self._db:
            self._db.executemany(
                "INSERT OR REPLACE INTO emb (key, vec) VALUES (?, ?)",
                [(k, json.dumps(v)) for k, v in items.items()],
            )

    def __len__(self) -> int:
        (anzahl,) = cast(tuple[int], self._db.execute("SELECT COUNT(*) FROM emb").fetchone())
        return anzahl

    def close(self) -> None:
        self._db.close()


class OllamaError(RuntimeError):
    """Ollama ist nicht erreichbar oder hat eine unerwartete Antwort geschickt."""


class OllamaEmbedder:
    """Embeddings über die Ollama-API ``POST /api/embed``.

    - **Batching:** Mehrere Texte pro Anfrage (``batch_size``), das ist auf der GPU deutlich
      schneller als einzeln.
    - **Hash-Cache:** Bereits berechnete Vektoren kommen aus dem ``EmbeddingCache``.
    - **Präfixe:** Manche Modelle (z. B. ``nomic-embed-text``) erwarten ``search_query:`` und
      ``search_document:`` vor dem Text; ``bge-m3`` braucht keine.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        batch_size: int = 32,
        cache: EmbeddingCache | None = None,
        timeout_s: float = 120.0,
        query_prefix: str = "",
        document_prefix: str = "",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size
        self.cache = cache if cache is not None else EmbeddingCache()
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix
        self._client = client or httpx.Client(timeout=timeout_s)

    @classmethod
    def for_model(cls, base_url: str, model: str, **kwargs: Any) -> OllamaEmbedder:
        """Setzt bekannte Präfixe passend zum Modell."""
        if model.startswith("nomic-embed-text"):
            kwargs.setdefault("query_prefix", "search_query: ")
            kwargs.setdefault("document_prefix", "search_document: ")
        return cls(base_url, model, **kwargs)

    @property
    def model_name(self) -> str:
        return self.model

    def _request(self, texts: list[str]) -> list[Vector]:
        try:
            antwort = self._client.post(
                f"{self.base_url}/api/embed", json={"model": self.model, "input": texts}
            )
            antwort.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaError(f"Embedding-Anfrage an {self.base_url} fehlgeschlagen: {e}") from e
        daten = cast(dict[str, Any], antwort.json())
        vektoren = daten.get("embeddings")
        if not isinstance(vektoren, list) or len(cast(list[Any], vektoren)) != len(texts):
            raise OllamaError("Ollama hat keine passende Anzahl Embeddings geliefert.")
        return [[float(x) for x in v] for v in cast(list[list[float]], vektoren)]

    def _embed(self, texts: Sequence[str]) -> list[Vector]:
        keys = [EmbeddingCache.key(self.model, t) for t in texts]
        bekannt = self.cache.get_many(keys)
        fehlend = list(dict.fromkeys(k for k in keys if k not in bekannt))
        text_zu_key = dict(zip(keys, texts, strict=True))
        for start in range(0, len(fehlend), self.batch_size):
            batch = fehlend[start : start + self.batch_size]
            neu = self._request([text_zu_key[k] for k in batch])
            frisch = dict(zip(batch, neu, strict=True))
            self.cache.put_many(frisch)
            bekannt.update(frisch)
        return [bekannt[k] for k in keys]

    def embed_documents(self, texts: Sequence[str]) -> list[Vector]:
        return self._embed([self.document_prefix + t for t in texts])

    def embed_query(self, text: str) -> Vector:
        return self._embed([self.query_prefix + text])[0]
