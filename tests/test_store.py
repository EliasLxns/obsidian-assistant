from pathlib import Path

import pytest

from assistant.index.store import ChromaStore, Fingerprint, InMemoryStore, VectorStore
from assistant.ingest.chunker import Chunk


def _chunks() -> list[Chunk]:
    return [
        Chunk("a.md#0", "a.md", "A", "A > Eins", "Text eins", ("t1", "t2"), ("B",)),
        Chunk("b.md#0", "b.md", "B", "", "Text zwei"),
    ]


@pytest.fixture(params=["memory", "chroma"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> VectorStore:
    if request.param == "memory":
        return InMemoryStore()
    return ChromaStore(tmp_path / "chroma", collection="test")


def test_upsert_query_und_metadaten(store: VectorStore) -> None:
    store.upsert(_chunks(), [[1.0, 0.0], [0.0, 1.0]], "bge-m3")
    assert store.count() == 2
    hits = store.query([0.9, 0.1], k=2)
    assert [h.chunk.id for h in hits] == ["a.md#0", "b.md#0"]
    assert hits[0].score > hits[1].score
    assert hits[0].chunk == _chunks()[0]  # Pfad, Überschrift, Tags, Links kommen zurück


def test_fingerprints_und_loeschen(store: VectorStore) -> None:
    chunks = _chunks()
    store.upsert(chunks, [[1.0, 0.0], [0.0, 1.0]], "bge-m3")
    assert store.fingerprints() == {
        "a.md#0": Fingerprint(chunks[0].hash, "bge-m3"),
        "b.md#0": Fingerprint(chunks[1].hash, "bge-m3"),
    }
    store.delete(["a.md#0"])
    assert store.count() == 1
    assert store.query([1.0, 0.0], k=5)[0].chunk.id == "b.md#0"


def test_alle_chunks(store: VectorStore) -> None:
    store.upsert(_chunks(), [[1.0, 0.0], [0.0, 1.0]], "bge-m3")
    assert sorted(store.alle_chunks(), key=lambda c: c.id) == _chunks()


def test_leerer_store(store: VectorStore) -> None:
    assert store.alle_chunks() == []
    assert store.query([1.0, 0.0], k=3) == []
    store.delete([])
    store.upsert([], [], "m")
    assert store.count() == 0


def test_chroma_bleibt_gespeichert(tmp_path: Path) -> None:
    ChromaStore(tmp_path / "c").upsert(_chunks(), [[1.0, 0.0], [0.0, 1.0]], "bge-m3")
    assert ChromaStore(tmp_path / "c").count() == 2
