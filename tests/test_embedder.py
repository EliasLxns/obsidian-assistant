import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from assistant.index.embedder import EmbeddingCache, FakeEmbedder, OllamaEmbedder, OllamaError
from assistant.index.store import cosine


def test_fake_embedder_ist_deterministisch_und_aehnlich() -> None:
    e = FakeEmbedder()
    a, b, c = e.embed_documents(["Docker Container starten", "Container starten", "Tomaten gießen"])
    assert a == FakeEmbedder().embed_query("Docker Container starten")
    assert cosine(a, b) > cosine(a, c)


class FakeOllama:
    """Simuliert ``/api/embed`` und zählt die Anfragen."""

    def __init__(self) -> None:
        self.anfragen: list[list[str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/embed"
        body: dict[str, Any] = json.loads(request.content)
        texte: list[str] = body["input"]
        self.anfragen.append(texte)
        return httpx.Response(200, json={"embeddings": [[float(len(t)), 1.0] for t in texte]})


def _embedder(fake: FakeOllama, cache: EmbeddingCache, batch_size: int = 2) -> OllamaEmbedder:
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    return OllamaEmbedder(
        "http://ollama:11434", "bge-m3", batch_size=batch_size, cache=cache, client=client
    )


def test_batching() -> None:
    fake = FakeOllama()
    vektoren = _embedder(fake, EmbeddingCache()).embed_documents(["a", "bb", "ccc", "dddd", "e"])
    assert [len(a) for a in fake.anfragen] == [2, 2, 1]
    assert [v[0] for v in vektoren] == [1.0, 2.0, 3.0, 4.0, 1.0]


def test_cache_spart_anfragen(tmp_path: Path) -> None:
    fake = FakeOllama()
    cache = EmbeddingCache(tmp_path / "cache.sqlite3")
    e = _embedder(fake, cache)
    e.embed_documents(["eins", "zwei"])
    e.embed_documents(["eins", "zwei", "drei", "drei"])
    assert fake.anfragen == [["eins", "zwei"], ["drei"]]
    assert len(cache) == 3

    # Ein neuer Embedder mit demselben Cache-File fragt gar nicht mehr.
    fake2 = FakeOllama()
    _embedder(fake2, EmbeddingCache(tmp_path / "cache.sqlite3")).embed_documents(["eins"])
    assert fake2.anfragen == []


def test_cache_unterscheidet_modelle() -> None:
    assert EmbeddingCache.key("bge-m3", "x") != EmbeddingCache.key("nomic-embed-text", "x")


def test_praefixe_fuer_nomic() -> None:
    fake = FakeOllama()
    client = httpx.Client(transport=httpx.MockTransport(fake.handler))
    e = OllamaEmbedder.for_model("http://o:11434", "nomic-embed-text", client=client)
    e.embed_query("frage")
    e.embed_documents(["text"])
    assert fake.anfragen == [["search_query: frage"], ["search_document: text"]]


def test_fehler_werden_zu_ollama_error() -> None:
    def kaputt(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nicht erreichbar", request=request)

    client = httpx.Client(transport=httpx.MockTransport(kaputt))
    with pytest.raises(OllamaError):
        OllamaEmbedder("http://o:11434", "bge-m3", client=client).embed_query("x")

    falsch = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(OllamaError):
        OllamaEmbedder("http://o:11434", "bge-m3", client=falsch).embed_query("x")


def test_cache_aus_anderem_thread(tmp_path: Path) -> None:
    """Die API nutzt den Cache aus dem Thread-Pool, der Watcher aus einem Timer-Thread."""
    import threading

    cache = EmbeddingCache(tmp_path / "cache.sqlite3")
    cache.put_many({"a": [1.0, 0.0]})
    ergebnis: list[dict[str, list[float]]] = []
    t = threading.Thread(target=lambda: ergebnis.append(cache.get_many(["a"])))
    t.start()
    t.join()
    assert ergebnis == [{"a": [1.0, 0.0]}]
