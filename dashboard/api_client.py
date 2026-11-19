"""Schmaler Client für die REST-API des Assistenten.

Das Dashboard spricht nur mit der API, nie direkt mit Vault, Chroma oder Ollama. So bleibt
es austauschbar (später React oder Blazor) und braucht nur ``streamlit`` und ``httpx``.
Die Typen spiegeln die Antworten der API (siehe ``/docs``).
"""

from __future__ import annotations

import os
from typing import Any, TypedDict, cast

import httpx

STANDARD_URL = "http://localhost:8080"


class Quelle(TypedDict):
    nr: int
    pfad: str
    titel: str
    ueberschrift: str
    score: float
    link: str
    auszug: str


class Antwort(TypedDict):
    antwort: str
    quellen: list[Quelle]
    modell: str
    dauer_s: float


class Indexlauf(TypedDict):
    notes: int
    chunks: int
    embedded: int
    unchanged: int
    deleted: int
    dauer_s: float
    zeitpunkt: str


class Status(TypedDict):
    version: str
    chunks: int
    vault: str
    embed_modell: str
    chat_modell: str
    ollama_erreichbar: bool
    letzter_indexlauf: Indexlauf | None


class Notiz(TypedDict):
    pfad: str
    titel: str
    art: str  # notiz | frage | beantwortet | pruefen
    geaendert: str
    link: str


class Pause(TypedDict):
    aktiv: bool
    bis: str | None
    grund: str


class Aktion(TypedDict):
    art: str  # einsortiert | pruefen | beantwortet | fehler
    quelle: str
    ziel: str
    details: str
    link: str | None


class Lauf(TypedDict):
    id: str
    start: str
    ende: str
    probelauf: bool
    pc: str
    hinweise: list[str]
    zaehler: dict[str, int]
    aktionen: list[Aktion]


class Inbox(TypedDict):
    offen: list[Notiz]
    pruefen: list[Notiz]
    naechster_lauf: str | None
    pause: Pause
    laeufe: list[Lauf]


class Anzahl(TypedDict):
    name: str
    anzahl: int


class ToterLink(TypedDict):
    notiz: str
    ziel: str
    link: str


class Pfad(TypedDict):
    pfad: str
    link: str


class Vault(TypedDict):
    vault: str
    notizen: int
    woerter: int
    links: int
    ordner: list[Anzahl]
    tags: list[Anzahl]
    tote_links: list[ToterLink]
    tote_links_anzahl: int
    ohne_links: list[Pfad]
    ohne_links_anzahl: int
    zuletzt: list[Notiz]


class ApiFehler(RuntimeError):
    """Die API antwortet nicht oder meldet einen Fehler. ``status`` 0: nicht erreichbar."""

    def __init__(self, status: int, meldung: str) -> None:
        super().__init__(meldung)
        self.status = status
        self.meldung = meldung


def _meldung(r: httpx.Response) -> str:
    """``detail`` aus einer Fehlerantwort, bei 422 die Meldungen der Prüfung."""
    try:
        detail: object = cast(dict[str, Any], r.json()).get("detail", r.text)
    except (ValueError, AttributeError):
        return r.text or f"HTTP {r.status_code}"
    if isinstance(detail, list):
        teile = cast(list[dict[str, Any]], detail)
        return "; ".join(str(t.get("msg", t)) for t in teile) or f"HTTP {r.status_code}"
    return str(detail)


class ApiClient:
    def __init__(self, basis_url: str | None = None, *, client: httpx.Client | None = None) -> None:
        self.basis_url = (basis_url or os.environ.get("API_URL") or STANDARD_URL).rstrip("/")
        # Antworten brauchen bei kaltem Modell bis zu einer Minute, Status nur Sekunden.
        self._client = client or httpx.Client(timeout=httpx.Timeout(10.0, read=180.0))

    def _anfrage(self, methode: str, pfad: str, json: Any = None) -> Any:
        try:
            r = self._client.request(methode, f"{self.basis_url}{pfad}", json=json)
        except httpx.HTTPError as e:
            raise ApiFehler(0, f"API unter {self.basis_url} nicht erreichbar ({e}).") from e
        if r.status_code >= 400:
            raise ApiFehler(r.status_code, _meldung(r))
        try:
            return r.json()
        except ValueError as e:  # z. B. API_URL zeigt auf einen anderen Dienst
            raise ApiFehler(r.status_code, f"{self.basis_url} antwortet nicht wie die API.") from e

    def status(self) -> Status:
        return cast(Status, self._anfrage("GET", "/status"))

    def fragen(self, frage: str, k: int = 5) -> Antwort:
        return cast(Antwort, self._anfrage("POST", "/ask", {"frage": frage, "k": k}))

    def suchen(self, frage: str, k: int = 8) -> list[Quelle]:
        daten = cast(dict[str, Any], self._anfrage("POST", "/search", {"frage": frage, "k": k}))
        return cast(list[Quelle], daten["quellen"])

    def reindex(self) -> Indexlauf:
        return cast(Indexlauf, self._anfrage("POST", "/reindex"))

    def inbox(self) -> Inbox:
        return cast(Inbox, self._anfrage("GET", "/inbox"))

    def vault(self) -> Vault:
        return cast(Vault, self._anfrage("GET", "/vault"))

    def pause_setzen(self, stunden: float | None, grund: str = "") -> Pause:
        return cast(
            Pause, self._anfrage("PUT", "/nachtjob/pause", {"stunden": stunden, "grund": grund})
        )

    def pause_aufheben(self) -> Pause:
        return cast(Pause, self._anfrage("DELETE", "/nachtjob/pause"))
