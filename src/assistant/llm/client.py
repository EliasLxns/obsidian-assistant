"""LLM: erzeugt Antworten aus einem Prompt.

``LLM`` ist das Interface, ``OllamaLLM`` nutzt ``POST /api/chat``,
``FakeLLM`` antwortet fest und merkt sich die Prompts (für Tests).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, cast

import httpx

from assistant.index.embedder import OllamaError


class LLM(Protocol):
    @property
    def model_name(self) -> str: ...

    def generate(self, prompt: str, system: str | None = None, *, json: bool = False) -> str:
        """Antwort auf ``prompt``. Mit ``json=True`` antwortet das Modell als JSON-Objekt."""
        ...


class FakeLLM:
    def __init__(
        self,
        answer: str = "Das steht in deinen Notizen [1].",
        json_answer: str = '{"ordner": null, "tags": [], "sicher": false, "grund": "Fake"}',
    ) -> None:
        self.answer = answer
        self.json_answer = json_answer
        self.prompts: list[tuple[str | None, str]] = []

    @property
    def model_name(self) -> str:
        return "fake-llm"

    def generate(self, prompt: str, system: str | None = None, *, json: bool = False) -> str:
        self.prompts.append((system, prompt))
        return self.json_answer if json else self.answer


class OllamaLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        temperature: float = 0.2,
        timeout_s: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_s)

    @property
    def model_name(self) -> str:
        return self.model

    def generate(self, prompt: str, system: str | None = None, *, json: bool = False) -> str:
        nachrichten: list[dict[str, str]] = []
        if system:
            nachrichten.append({"role": "system", "content": system})
        nachrichten.append({"role": "user", "content": prompt})
        try:
            anfrage: dict[str, Any] = {
                "model": self.model,
                "messages": nachrichten,
                "stream": False,
                "options": {"temperature": self.temperature},
            }
            if json:
                anfrage["format"] = "json"
            antwort = self._client.post(f"{self.base_url}/api/chat", json=anfrage)
            antwort.raise_for_status()
        except httpx.HTTPError as e:
            raise OllamaError(f"Chat-Anfrage an {self.base_url} fehlgeschlagen: {e}") from e
        daten = cast(dict[str, Any], antwort.json())
        nachricht = cast(dict[str, Any], daten.get("message") or {})
        inhalt = nachricht.get("content")
        if not isinstance(inhalt, str):
            raise OllamaError("Ollama hat keine Antwort geliefert.")
        return inhalt.strip()


def ollama_reachable(
    base_url: str, *, timeout_s: float = 2.0, client: httpx.Client | None = None
) -> bool:
    """Antwortet Ollama? Kurzer Timeout, damit ``/status`` bei schlafendem Gaming-PC schnell ist."""
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        if client is not None:
            return client.get(url).is_success
        with httpx.Client(timeout=timeout_s) as eigener:  # wird danach geschlossen
            return eigener.get(url).is_success
    except httpx.HTTPError:
        return False


def unload_models(
    base_url: str,
    models: Sequence[str],
    *,
    timeout_s: float = 10.0,
    client: httpx.Client | None = None,
) -> list[str]:
    """Entlädt Modelle sofort aus dem VRAM (``keep_alive: 0``), damit die GPU frei ist.

    Gibt die Modelle zurück, die sich nicht entladen ließen. Fehler brechen nichts ab:
    Ollama entlädt ohnehin nach fünf Minuten von selbst.
    """
    fehler: list[str] = []
    eigener = client is None
    c = client or httpx.Client(timeout=timeout_s)
    try:
        for modell in models:
            # Embedding-Modelle kennen /api/generate nicht, /api/embed mit leerer Eingabe schon.
            versuche: list[tuple[str, dict[str, Any]]] = [
                ("/api/generate", {"model": modell, "keep_alive": 0}),
                ("/api/embed", {"model": modell, "input": [], "keep_alive": 0}),
            ]
            for pfad, nutzlast in versuche:
                try:
                    if c.post(f"{base_url.rstrip('/')}{pfad}", json=nutzlast).is_success:
                        break
                except httpx.HTTPError:
                    pass
            else:
                fehler.append(modell)
    finally:
        if eigener:
            c.close()
    return fehler


def ollama_busy(
    base_url: str, *, timeout_s: float = 5.0, client: httpx.Client | None = None
) -> bool:
    """Hat Ollama gerade ein Modell geladen (``/api/ps``)? Dann läuft oder lief eben eine Anfrage.

    Nicht erreichbar zählt als „nicht beschäftigt“.
    """
    url = f"{base_url.rstrip('/')}/api/ps"
    try:
        if client is not None:
            antwort = client.get(url)
        else:
            with httpx.Client(timeout=timeout_s) as eigener:
                antwort = eigener.get(url)
        daten = cast(dict[str, Any], antwort.json()) if antwort.is_success else {}
    except (httpx.HTTPError, ValueError):
        return False
    return bool(daten.get("models"))
