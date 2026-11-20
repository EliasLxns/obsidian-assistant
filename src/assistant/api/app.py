"""REST-API für Dashboard und Obsidian-Plugin.

- ``POST /ask``: Frage beantworten, mit Quellen als ``obsidian://``-Links
- ``POST /search``: nur suchen, ohne Chat-Modell (mit ``SEARCH_MODE=hybrid`` auch ohne Ollama)
- ``GET /status``: Index-Größe, Modelle, letzter Indexlauf, ist Ollama erreichbar?
- ``POST /reindex``: Vault neu einlesen (nur Geändertes wird eingebettet)
- ``GET /inbox``: offene Inbox-Notizen, „Prüfen“-Ordner, letzte Nachtläufe, Pause
- ``GET /vault``: Vault-Statistik (Notizen, Ordner, Tags, tote Links, zuletzt geändert)
- ``PUT /nachtjob/pause`` / ``DELETE /nachtjob/pause``: Gaming-Schutz ein- und ausschalten

Die API liest den Vault nur. Einzige Schreibstelle ist der Pause-Schalter im Zustandsordner
des Nachtjobs, nie der Vault.

Die Endpunkte sind bewusst synchron (``def``): FastAPI führt sie in einem Thread-Pool aus,
und die Bausteine (httpx, Chroma) sind ohnehin blockierend.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from assistant import __version__
from assistant.components import Components
from assistant.index.embedder import OllamaError
from assistant.index.store import Hit
from assistant.ingest.indexer import IndexReport, index_vault
from assistant.links import obsidian_url
from assistant.llm.answer import answer_question
from assistant.llm.client import ollama_reachable
from assistant.nightly.guard import Pause, aktive_pause, pause_aufheben, pause_setzen
from assistant.nightly.uebersicht import InboxNotiz, inbox_uebersicht
from assistant.retrieval.search import Retriever
from assistant.statistik import vault_statistik

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
    modus: str  # vektor | bm25 | hybrid; bm25 auch, wenn hybrid ohne Ollama weitersuchen musste


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
    version: str
    chunks: int
    vault: str
    embed_modell: str
    chat_modell: str
    ollama_erreichbar: bool
    letzter_indexlauf: IndexlaufOut | None


class NotizOut(BaseModel):
    pfad: str
    titel: str
    art: str  # notiz | frage | beantwortet | pruefen
    geaendert: datetime
    link: str


class PauseOut(BaseModel):
    aktiv: bool
    bis: datetime | None = None  # None bei aktiv: bis zum Aufheben
    grund: str = ""


class PauseIn(BaseModel):
    # None: bis zum Aufheben. Mindestens eine Minute, sonst wäre die Pause sofort vorbei.
    stunden: float | None = Field(default=None, ge=1 / 60, le=24 * 14)
    grund: str = Field(default="", max_length=200)


class AktionOut(BaseModel):
    art: str
    quelle: str
    ziel: str
    details: str
    link: str | None  # zur Notiz am neuen Ort


class LaufOut(BaseModel):
    id: str
    start: str
    ende: str
    probelauf: bool
    pc: str
    hinweise: list[str]
    zaehler: dict[str, int]
    aktionen: list[AktionOut]


class InboxOut(BaseModel):
    offen: list[NotizOut]
    pruefen: list[NotizOut]
    naechster_lauf: datetime | None
    pause: PauseOut
    laeufe: list[LaufOut]


class Anzahl(BaseModel):
    name: str
    anzahl: int


class PfadOut(BaseModel):
    pfad: str
    link: str


class ToterLinkOut(BaseModel):
    notiz: str
    ziel: str
    link: str


class VaultOut(BaseModel):
    vault: str
    notizen: int
    woerter: int
    links: int
    ordner: list[Anzahl]
    tags: list[Anzahl]
    tote_links: list[ToterLinkOut]
    tote_links_anzahl: int
    ohne_links: list[PfadOut]
    ohne_links_anzahl: int
    zuletzt: list[NotizOut]


def _pause_out(p: Pause | None) -> PauseOut:
    return PauseOut(aktiv=False) if p is None else PauseOut(aktiv=True, bis=p.bis, grund=p.grund)


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


def create_app(
    components: Components,
    ping: Callable[[], bool] | None = None,
    uhr: Callable[[], datetime] = datetime.now,
) -> FastAPI:
    """Baut die App um fertige Bausteine herum. ``ping`` prüft, ob Ollama antwortet,
    ``uhr`` liefert die Ortszeit ohne Zeitzone (wie im Nachtjob, in Tests fest)."""
    c = components
    s = c.settings
    pruefe_ollama = ping or (lambda: ollama_reachable(s.ollama_url))
    retriever = Retriever(
        c.embedder,
        c.store,
        modus=s.suchmodus,
        erreichbar=pruefe_ollama,
        link_erweiterung=s.link_erweiterung,
    )
    index_sperre = threading.Lock()  # nie zwei Indexläufe gleichzeitig
    letzter: list[IndexlaufOut] = []

    app = FastAPI(
        title="Obsidian-Assistent",
        version=__version__,
        description="Fragen an den Obsidian-Vault, komplett lokal.",
    )

    def _index_nicht_leer() -> None:
        if c.store.count() == 0:
            raise HTTPException(409, "Der Index ist leer. Erst POST /reindex aufrufen.")

    def _link(pfad: str) -> str:
        return obsidian_url(s.vault_name, pfad)

    def _notiz_out(n: InboxNotiz) -> NotizOut:
        return NotizOut(
            pfad=n.pfad, titel=n.titel, art=n.art, geaendert=n.geaendert, link=_link(n.pfad)
        )

    def _ollama_fehler(e: OllamaError) -> HTTPException:
        return HTTPException(503, f"{e} Läuft Ollama unter {s.ollama_url}? Ist der Gaming-PC wach?")

    @app.post("/search")
    def search(body: FrageIn) -> SucheOut:
        _index_nicht_leer()
        try:
            hits, modus = retriever.search_notes_mit_modus(body.frage, body.k)
        except OllamaError as e:
            raise _ollama_fehler(e) from e
        return SucheOut(quellen=_quellen(hits, s.vault_name), modus=modus)

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
            version=__version__,
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

    @app.get("/inbox")
    def inbox() -> InboxOut:
        try:
            u = inbox_uebersicht(s, uhr())
        except FileNotFoundError as e:
            raise HTTPException(500, str(e)) from e
        laeufe = [
            LaufOut(
                id=lauf.id,
                start=lauf.start,
                ende=lauf.ende,
                probelauf=lauf.probelauf,
                pc=lauf.pc,
                hinweise=lauf.hinweise,
                zaehler=lauf.zaehler,
                aktionen=[
                    AktionOut(
                        art=a.art,
                        quelle=a.quelle,
                        ziel=a.ziel,
                        details=a.details,
                        # Im Probelauf wurde nichts verschoben, der Link zeigte ins Leere.
                        link=_link(a.ziel) if a.ziel and not lauf.probelauf else None,
                    )
                    for a in lauf.aktionen
                ],
            )
            for lauf in u.laeufe
        ]
        return InboxOut(
            offen=[_notiz_out(n) for n in u.offen],
            pruefen=[_notiz_out(n) for n in u.pruefen],
            naechster_lauf=u.naechster_lauf,
            pause=_pause_out(u.pause),
            laeufe=laeufe,
        )

    @app.get("/vault")
    def vault() -> VaultOut:
        try:
            st = vault_statistik(s.vault_path)
        except FileNotFoundError as e:
            raise HTTPException(500, str(e)) from e
        return VaultOut(
            vault=s.vault_name,
            notizen=st.notizen,
            woerter=st.woerter,
            links=st.links,
            ordner=[Anzahl(name=n, anzahl=a) for n, a in st.ordner],
            tags=[Anzahl(name=n, anzahl=a) for n, a in st.tags],
            tote_links=[
                ToterLinkOut(notiz=t.notiz, ziel=t.ziel, link=_link(t.notiz)) for t in st.tote_links
            ],
            tote_links_anzahl=st.tote_links_anzahl,
            ohne_links=[PfadOut(pfad=p, link=_link(p)) for p in st.ohne_links],
            ohne_links_anzahl=st.ohne_links_anzahl,
            zuletzt=[
                _notiz_out(InboxNotiz(n.pfad, n.titel, "notiz", n.geaendert)) for n in st.zuletzt
            ],
        )

    @app.get("/nachtjob/pause")
    def pause_lesen() -> PauseOut:
        return _pause_out(aktive_pause(s.nightly_state_path, uhr()))

    @app.put("/nachtjob/pause")
    def pause_an(body: PauseIn) -> PauseOut:
        """Gaming-Schutz: Der Nachtjob weckt den PC nicht, solange die Pause gilt."""
        bis = None
        if body.stunden:
            bis = (uhr() + timedelta(hours=body.stunden)).replace(microsecond=0)
        try:
            pause_setzen(s.nightly_state_path, bis, body.grund.strip())
        except OSError as e:
            raise HTTPException(500, f"Pause konnte nicht gespeichert werden: {e}") from e
        return _pause_out(aktive_pause(s.nightly_state_path, uhr()))

    @app.delete("/nachtjob/pause")
    def pause_aus() -> PauseOut:
        try:
            pause_aufheben(s.nightly_state_path)
        except OSError as e:
            raise HTTPException(500, f"Pause konnte nicht aufgehoben werden: {e}") from e
        return _pause_out(None)

    return app
