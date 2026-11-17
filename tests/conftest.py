from pathlib import Path

import pytest

from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.ingest.indexer import index_vault

ROOT = Path(__file__).resolve().parent.parent
DEMO_VAULT = ROOT / "demo_vault"
QUESTIONS = ROOT / "eval" / "questions.yaml"


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def demo_store(embedder: FakeEmbedder) -> InMemoryStore:
    store = InMemoryStore()
    index_vault(DEMO_VAULT, embedder, store)
    return store
