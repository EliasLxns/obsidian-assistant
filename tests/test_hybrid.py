"""BM25, Reciprocal Rank Fusion und die Suchmodi des Retrievers (Phase 5)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from assistant.api import create_app
from assistant.components import Components
from assistant.config import SUCHMODI as SUCHMODI_CONFIG
from assistant.config import Settings, load_settings
from assistant.index.embedder import FakeEmbedder, OllamaError, Vector
from assistant.index.store import Hit, InMemoryStore
from assistant.ingest.chunker import Chunk
from assistant.llm.client import FakeLLM
from assistant.retrieval.bm25 import Bm25, stamm, woerter
from assistant.retrieval.links import LinkGraph, einfuegen
from assistant.retrieval.search import SUCHMODI, Retriever, rrf, suchmodus


def _chunk(pfad: str, text: str, nr: int = 0) -> Chunk:
    return Chunk(
        id=f"{pfad}#{nr}", path=pfad, title=pfad.removesuffix(".md"), heading="", text=text
    )


# --- BM25 -------------------------------------------------------------------------------


def test_woerter_ohne_stoppwoerter_und_mit_stamm() -> None:
    assert woerter("Wie starte ich die Container?") == ["start", "contain"]
    assert woerter("restart: unless-stopped auf Port 11434") == [
        "restart",
        "unles",  # Stamm, Anfrage und Text werden gleich gekürzt
        "stopped",
        "port",
        "11434",
    ]
    assert stamm("containern") == stamm("container")
    assert stamm("ab") == "ab"  # kurze Wörter bleiben


def test_bm25_seltener_begriff_gewinnt() -> None:
    chunks = [
        _chunk("Knie.md", "ITBS heißt Iliotibialband-Syndrom. Knie schmerzt beim Laufen."),
        _chunk("Laufen.md", "Laufen im Winter. Laufen im Sommer. Laufen macht Spaß."),
        _chunk("Garten.md", "Tomaten brauchen Sonne."),
    ]
    bm = Bm25(chunks)
    assert [h.chunk.path for h in bm.search("Was ist ITBS?", 3)] == ["Knie.md"]
    treffer = bm.search("Knie beim Laufen", 3)
    assert treffer[0].chunk.path == "Knie.md"  # zwei Begriffe schlagen einen häufigen
    assert {h.chunk.path for h in treffer} == {"Knie.md", "Laufen.md"}  # Garten: Score 0
    assert bm.search("der die das", 3) == []  # nur Stoppwörter
    assert Bm25([]).search("ITBS", 3) == []


def test_bm25_zaehlt_titel_mit() -> None:
    bm = Bm25([_chunk("Tailscale.md", "Exit Node einrichten."), _chunk("Andere.md", "Text.")])
    assert bm.search("tailscale", 1)[0].chunk.path == "Tailscale.md"


# --- RRF --------------------------------------------------------------------------------


def test_rrf_belohnt_treffer_in_beiden_listen() -> None:
    a, b, c = _chunk("a.md", "a"), _chunk("b.md", "b"), _chunk("c.md", "c")
    vektor = [Hit(a, 0.9), Hit(b, 0.8)]
    stichwort = [Hit(c, 12.0), Hit(b, 3.0)]
    fusion = rrf(vektor, stichwort)
    assert [h.chunk.path for h in fusion] == ["b.md", "a.md", "c.md"]
    assert fusion[0].score == pytest.approx(1 / 62 + 1 / 62, abs=1e-6)


# --- Retriever --------------------------------------------------------------------------


class _OllamaWeg(FakeEmbedder):
    def embed_query(self, text: str) -> Vector:
        raise OllamaError("Verbindung abgelehnt")


def test_modi_finden_exakten_begriff(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    for modus in ("vektor", "bm25", "hybrid"):
        hits = Retriever(embedder, demo_store, modus=suchmodus(modus)).search_notes("ITBS", k=3)
        assert hits[0].chunk.path == "03 Wissen/Laufen/Läuferknie.md", modus
        assert len({h.chunk.path for h in hits}) == len(hits)


def test_bm25_braucht_kein_ollama(demo_store: InMemoryStore) -> None:
    r = Retriever(_OllamaWeg(), demo_store, modus="bm25")
    assert r.search("Eisheilige", 2)[0].chunk.path.endswith("Aussaatkalender.md")


def test_hybrid_sucht_ohne_ollama_mit_bm25_weiter(demo_store: InMemoryStore) -> None:
    hits, modus = Retriever(_OllamaWeg(), demo_store, modus="hybrid").search_notes_mit_modus(
        "Eisheilige", 3
    )
    assert modus == "bm25"
    assert hits[0].chunk.path.endswith("Aussaatkalender.md")
    with pytest.raises(OllamaError):  # reine Vektorsuche scheitert weiter sichtbar
        Retriever(_OllamaWeg(), demo_store, modus="vektor").search_notes("Eisheilige", 3)


class _Zaehler(FakeEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.anfragen = 0

    def embed_query(self, text: str) -> Vector:
        self.anfragen += 1
        return super().embed_query(text)


def test_hybrid_fragt_ollama_nicht_wenn_ping_scheitert(demo_store: InMemoryStore) -> None:
    """Schläft der PC, wartet die Suche nicht auf den Ollama-Timeout."""
    emb, pings, jetzt = _Zaehler(), list[int](), [0.0]
    r = Retriever(
        emb,
        demo_store,
        modus="hybrid",
        erreichbar=lambda: pings.append(1) or False,
        uhr=lambda: jetzt[0],
    )
    assert r.search_notes_mit_modus("Eisheilige", 3)[1] == "bm25"
    assert r.search_mit_modus("Eisheilige", 3)[1] == "bm25"
    assert emb.anfragen == 0 and len(pings) == 1  # Ergebnis 30 s gemerkt
    jetzt[0] = 31.0
    r.search("Eisheilige", 3)
    assert len(pings) == 2


def test_eval_ohne_rueckfall_scheitert_sichtbar(demo_store: InMemoryStore) -> None:
    r = Retriever(_OllamaWeg(), demo_store, modus="hybrid", rueckfall=False)
    with pytest.raises(OllamaError):
        r.search_notes("Eisheilige", 3)


def test_bm25_index_folgt_dem_store(embedder: FakeEmbedder) -> None:
    store = InMemoryStore()
    jetzt = [0.0]
    r = Retriever(embedder, store, modus="bm25", uhr=lambda: jetzt[0])
    assert r.search("Feuchtesensor", 1) == []
    neu = _chunk("Sensor.md", "Feuchtesensor am Hochbeet")
    store.upsert([neu], [embedder.embed_query(neu.embed_text)], "fake")
    assert r.search("Feuchtesensor", 1)[0].chunk.path == "Sensor.md"  # neue Anzahl
    geaendert = _chunk("Sensor.md", "Bodenfeuchte am Hochbeet")  # gleiche ID und Anzahl
    store.upsert([geaendert], [embedder.embed_query(geaendert.embed_text)], "fake")
    assert r.search("Bodenfeuchte", 1) == []  # noch der alte Index
    jetzt[0] = 61.0
    assert r.search("Bodenfeuchte", 1)[0].chunk.path == "Sensor.md"  # nach einer Minute neu
    store.delete([neu.id])
    assert r.search("Feuchtesensor", 1) == []


def test_unbekannter_modus() -> None:
    with pytest.raises(ValueError, match="Unbekannter Suchmodus"):
        suchmodus("semantisch")


def test_suchmodus_aus_env() -> None:
    assert SUCHMODI_CONFIG == SUCHMODI
    with pytest.raises(ValueError, match="SEARCH_MODE='vector' ist ungültig"):
        load_settings(environ={"SEARCH_MODE": "vector"}, env_file=Path("fehlt.env"))
    assert load_settings(environ={"SEARCH_MODE": " Hybrid "}).suchmodus == "hybrid"
    standard = load_settings(environ={}, env_file=Path("fehlt.env"))
    assert standard.suchmodus == "hybrid" and not standard.link_erweiterung
    assert load_settings(environ={"LINK_EXPANSION": "ja"}, env_file=Path("x")).link_erweiterung


def test_api_search_ohne_ollama(demo_store: InMemoryStore) -> None:
    c = Components(
        settings=Settings(suchmodus="hybrid"),
        embedder=_OllamaWeg(),
        store=demo_store,
        llm=FakeLLM("x"),
    )
    client = TestClient(create_app(c, ping=lambda: False))
    daten = client.post("/search", json={"frage": "Eisheilige", "k": 3}).json()
    assert daten["modus"] == "bm25"
    assert daten["quellen"][0]["pfad"].endswith("Aussaatkalender.md")


# --- Link-Erweiterung --------------------------------------------------------------------


def _verlinkt(pfad: str, text: str, *links: str) -> Chunk:
    titel = pfad.removesuffix(".md")
    return Chunk(f"{pfad}#0", pfad, titel, "", text, links=links)


def test_linkgraph_loest_wie_obsidian_auf() -> None:
    g = LinkGraph([_verlinkt("03 Wissen/Docker/Compose.md", "x"), _verlinkt("Compose.md", "y")])
    assert g.ziel("compose") == "Compose.md"  # gleicher Name: kürzester Pfad
    assert g.ziel("03 Wissen/Docker/Compose#Starten") == "03 Wissen/Docker/Compose.md"
    assert g.ziel("Gibt es nicht") is None


def test_verlinkte_notizen_kommen_hinter_die_besten() -> None:
    chunks = [
        _verlinkt("Bericht.md", "Halbmarathon Zielzeit geschafft", "Plan"),
        _verlinkt("Plan.md", "Trainingsplan mit langen Läufen"),
        _verlinkt("A.md", "Halbmarathon a"),
        _verlinkt("B.md", "Halbmarathon b"),
        _verlinkt("C.md", "Halbmarathon c"),
    ]
    store = InMemoryStore()
    emb = FakeEmbedder()
    store.upsert(chunks, emb.embed_documents([c.embed_text for c in chunks]), "fake")
    ohne = Retriever(emb, store, modus="bm25").search_notes("Halbmarathon Zielzeit", 5)
    mit = Retriever(emb, store, modus="bm25", link_erweiterung=True).search_notes(
        "Halbmarathon Zielzeit", 5
    )
    assert "Plan.md" not in [h.chunk.path for h in ohne]  # kein gemeinsames Wort
    pfade = [h.chunk.path for h in mit]
    assert pfade[0] == "Bericht.md"  # die ersten Plätze bleiben
    assert pfade.index("Plan.md") == 3  # direkt hinter den besten drei
    assert len(pfade) == len(set(pfade))


def test_einfuegen_ohne_links_und_ohne_doppelte() -> None:
    a, b = _verlinkt("a.md", "a"), _verlinkt("b.md", "b")
    treffer = [Hit(a, 1.0), Hit(b, 0.5)]
    assert einfuegen(treffer, []) == treffer
    assert einfuegen(treffer, [Hit(b, 0.0)]) == treffer  # b ist schon oben


def test_vektor_modus_ignoriert_links(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    mit = Retriever(embedder, demo_store, modus="vektor", link_erweiterung=True)
    ohne = Retriever(embedder, demo_store, modus="vektor")
    assert mit.search_notes("Halbmarathon", 5) == ohne.search_notes("Halbmarathon", 5)
