"""Bausteine einer laufenden Instanz: Embedder, VectorStore, LLM.

CLI, API und Watcher holen sich ihre Bausteine aus einer ``ComponentsFactory``.
Im Normalbetrieb sind das Ollama und ChromaDB, in Tests Fakes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from assistant.config import Settings
from assistant.index.embedder import Embedder, EmbeddingCache, OllamaEmbedder
from assistant.index.store import ChromaStore, VectorStore
from assistant.llm.client import LLM, OllamaLLM


@dataclass
class Components:
    settings: Settings
    embedder: Embedder
    store: VectorStore
    llm: LLM


ComponentsFactory = Callable[[Settings], Components]


def build_store(settings: Settings) -> VectorStore:
    """Chroma per HTTP, wenn ``CHROMA_HOST`` gesetzt ist (Docker), sonst als lokale Datei."""
    if settings.chroma_host:
        return ChromaStore(host=settings.chroma_host, port=settings.chroma_port)
    return ChromaStore(settings.chroma_path)


def default_components(settings: Settings) -> Components:
    cache = EmbeddingCache(settings.cache_path)
    return Components(
        settings=settings,
        embedder=OllamaEmbedder.for_model(
            settings.ollama_url, settings.embed_model, cache=cache, timeout_s=settings.timeout_s
        ),
        store=build_store(settings),
        llm=OllamaLLM(settings.ollama_url, settings.chat_model, timeout_s=settings.timeout_s),
    )
