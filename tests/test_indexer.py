import shutil
from pathlib import Path

from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.ingest.indexer import index_vault
from tests.conftest import DEMO_VAULT


def test_index_ist_inkrementell(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    embedder, store = FakeEmbedder(), InMemoryStore()

    erst = index_vault(vault, embedder, store)
    assert erst.notes == 25
    assert erst.embedded == erst.chunks == store.count()

    zweit = index_vault(vault, embedder, store)
    assert (zweit.embedded, zweit.unchanged, zweit.deleted) == (0, erst.chunks, 0)

    # Eine Notiz ändern, eine löschen
    compose = vault / "03 Wissen/Docker/Compose.md"
    compose.write_text(compose.read_text(encoding="utf-8") + "\nNeuer Satz.\n", encoding="utf-8")
    (vault / "03 Wissen/Garten/Kompost.md").unlink()
    dritt = index_vault(vault, embedder, store)
    assert dritt.embedded == 1
    assert dritt.deleted > 0
    assert not any(f.startswith("03 Wissen/Garten/Kompost.md") for f in store.fingerprints())


def test_modellwechsel_bettet_alles_neu_ein() -> None:
    store = InMemoryStore()
    index_vault(DEMO_VAULT, FakeEmbedder(dim=64), store)
    neu = index_vault(DEMO_VAULT, FakeEmbedder(dim=128), store)
    assert neu.unchanged == 0
