import shutil
from pathlib import Path

import pytest

from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.ingest.indexer import index_notes, index_vault, path_of
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


def test_index_notes_nur_geaenderte_dateien(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    embedder, store = FakeEmbedder(), InMemoryStore()
    gesamt = index_vault(vault, embedder, store)

    # Unveränderte Notiz: nichts passiert
    compose = vault / "03 Wissen/Docker/Compose.md"
    r = index_notes(vault, [compose], embedder, store)
    assert (r.notes, r.embedded, r.deleted) == (1, 0, 0)

    # Geänderte, neue, gelöschte Notiz und eine Datei außerhalb des Index in einem Lauf
    compose.write_text(compose.read_text(encoding="utf-8") + "\nNeuer Satz.\n", encoding="utf-8")
    neu = vault / "00 Inbox/Neue Idee.md"
    neu.write_text("# Neue Idee\n\nKompost im Winter abdecken.\n", encoding="utf-8")
    kompost = vault / "03 Wissen/Garten/Kompost.md"
    kompost.unlink()
    konfig = vault / ".obsidian/app.json"
    konfig.parent.mkdir(exist_ok=True)
    konfig.write_text("{}", encoding="utf-8")

    vorher = embedder.calls
    r = index_notes(vault, [compose, neu, kompost, konfig], embedder, store)
    assert r.notes == 2
    assert r.embedded == 2  # ein geänderter Chunk in Compose, einer in der neuen Notiz
    assert embedder.calls - vorher == 2
    assert r.deleted > 0
    pfade = {path_of(i) for i in store.fingerprints()}
    assert "00 Inbox/Neue Idee.md" in pfade
    assert "03 Wissen/Garten/Kompost.md" not in pfade

    # Ergebnis ist dasselbe wie ein voller Lauf
    voll = index_vault(vault, embedder, store)
    assert (voll.embedded, voll.deleted) == (0, 0)
    assert voll.chunks == store.count() != gesamt.chunks


def test_index_notes_mit_relativem_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(DEMO_VAULT, vault)
    monkeypatch.chdir(tmp_path)
    store = InMemoryStore()
    r = index_notes(Path("vault"), [vault / "03 Wissen/Docker/Compose.md"], FakeEmbedder(), store)
    assert r.notes == 1 and store.count() == r.chunks > 0


def test_path_of() -> None:
    assert path_of("03 Wissen/C#.md#2") == "03 Wissen/C#.md"
