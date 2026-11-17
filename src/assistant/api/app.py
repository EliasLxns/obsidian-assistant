"""REST-API für Dashboard und Obsidian-Plugin.

- ``POST /ask``: Frage beantworten, mit Quellen als ``obsidian://``-Links
- ``POST /search``: nur suchen, ohne Chat-Modell (geht auch, wenn nur Embeddings laufen)
- ``GET /status``: Index-Größe, Modelle, letzter Indexlauf, ist Ollama erreichbar?
- ``POST /reindex``: Vault neu einlesen (nur Geändertes wird eingebettet)

Die Endpunkte sind bewusst synchron (``def``): FastAPI führt sie in einem Thread-Pool aus,
und die Bausteine (httpx, Chroma) sind ohnehin blockierend.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from assistant.components import Components
from assistant.index.embedder import OllamaError
from assistant.index.store import Hit
from assistant.ingest.indexer import IndexReport, index_vault
from assistant.links import obsidian_url
from assistant.llm.answer import answer_question
from assistant.llm.client import ollama_reachable
from assistant.retrieval.search import Retriever

AUSZUG_ZEICHEN = 300


class FrageIn(BaseModel):
    frage: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)


class Quelle(BaseModel):
    nr: int
    pfad: str
    titel: str
    ueberschrift: str
    score: float
    link: str  # obsidian://open?... öffnet die Notiz direkt
    auszug: str


class SucheOut(BaseModel):
    quellen: list[Quelle]


class AntwortOut(BaseModel):
    antwort: str
    quellen: list[Quelle]
    modell: str
    dauer_s: float


class IndexlaufOut(BaseModel):
    notes: int
    chunks: int
    embedded: int
    unchanged: int
    deleted: int
    dauer_s: float
    zeitpunkt: datetime


class StatusOut(BaseModel):
    chunks: int
    vault: str
    embed_modell: str
    chat_modell: str
    ollama_erreichbar: bool
    letzter_indexlauf: IndexlaufOut | None


def _auszug(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= AUSZUG_ZEICHEN else text[: AUSZUG_ZEICHEN - 1].rstrip() + "…"


def _quellen(hits: list[Hit], vault_name: str) -> list[Quelle]:
    return [
        Quelle(
            nr=nr,
            pfad=h.chunk.path,
            titel=h.chunk.title,
            ueberschrift=h.chunk.heading,
            score=round(h.score, 4),
            link=obsidian_url(vault_name, h.chunk.path),
            auszug=_auszug(h.chunk.text),
        )
        for nr, h in enumerate(hits, start=1)
    ]


def create_app(components: Components, ping: Callable[[], bool] | None = None) -> FastAPI:
    """Baut die App um fertige Bausteine herum. ``ping`` prüft, ob Ollama antwortet."""
    c = components
    s = c.settings
    pruefe_ollama = ping or (lambda: ollama_reachable(s.ollama_url))
    retriever = Retriever(c.embedder, c.store)
    index_sperre = threading.Lock()  # nie zwei Indexläufe gleichzeitig
    letzter: list[IndexlaufOut] = []

    app = FastAPI(
        title="Obsidian-Assistent",
        version="0.2.0",
        description="Fragen an den Obsidian-Vault, komplett lokal.",
    )

    def _index_nicht_leer() -> None:
        if c.store.count() == 0:
            raise HTTPException(409, "Der Index ist leer. Erst POST /reindex aufrufen.")

    def _ollama_fehler(e: OllamaError) -> HTTPException:
        return HTTPException(503, f"{e} Läuft Ollama unter {s.ollama_url}? Ist der Gaming-PC wach?")

    @app.post("/search")
    def search(body: FrageIn) -> SucheOut:
        _index_nicht_leer()
        try:
            hits = retriever.search_notes(body.frage, body.k)
        except OllamaError as e:
            raise _ollama_fehler(e) from e
        return SucheOut(quellen=_quellen(hits, s.vault_name))

    @app.post("/ask")
    def ask(body: FrageIn) -> AntwortOut:
        _index_nicht_leer()
        start = time.perf_counter()
        try:
            antwort = answer_question(body.frage, retriever, c.llm, body.k)
        except OllamaError as e:
            raise _ollama_fehler(e) from e
        return AntwortOut(
            antwort=antwort.text,
            quellen=_quellen(antwort.sources, s.vault_name),
            modell=c.llm.model_name,
            dauer_s=round(time.perf_counter() - start, 2),
        )

    @app.get("/status")
    def status() -> StatusOut:
        return StatusOut(
            chunks=c.store.count(),
            vault=s.vault_name,
            embed_modell=c.embedder.model_name,
            chat_modell=c.llm.model_name,
            ollama_erreichbar=pruefe_ollama(),
            letzter_indexlauf=letzter[-1] if letzter else None,
        )

    @app.post("/reindex")
    def reindex() -> IndexlaufOut:
        if not index_sperre.acquire(blocking=False):
            raise HTTPException(409, "Es läuft bereits ein Indexlauf.")
        try:
            start = time.perf_counter()
            bericht: IndexReport = index_vault(s.vault_path, c.embedder, c.store)
        except FileNotFoundError as e:
            raise HTTPException(500, str(e)) from e
        except OllamaError as e:
            raise _ollama_fehler(e) from e
        finally:
            index_sperre.release()
        lauf = IndexlaufOut(
            **asdict(bericht),
            dauer_s=round(time.perf_counter() - start, 2),
            zeitpunkt=datetime.now(UTC),
        )
        letzter[:] = [lauf]
        return lauf

    return app
