"""LLM: erzeugt Antworten aus einem Prompt.

``LLM`` ist das Interface, ``OllamaLLM`` nutzt ``POST /api/chat``,
``FakeLLM`` antwortet fest und merkt sich die Prompts (für Tests).
"""

from __future__ import annotations

from typing import Any, Protocol, cast

import httpx

from assistant.index.embedder import OllamaError


class LLM(Protocol):
    @property
    def model_name(self) -> str: ...

    def generate(self, prompt: str, system: str | None = None) -> str: ...


class FakeLLM:
    def __init__(self, answer: str = "Das steht in deinen Notizen [1].") -> None:
        self.answer = answer
        self.prompts: list[tuple[str | None, str]] = []

    @property
    def model_name(self) -> str:
        return "fake-llm"

    def generate(self, prompt: str, system: str | None = None) -> str:
        self.prompts.append((system, prompt))
        return self.answer


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

    def generate(self, prompt: str, system: str | None = None) -> str:
        nachrichten: list[dict[str, str]] = []
        if system:
            nachrichten.append({"role": "system", "content": system})
        nachrichten.append({"role": "user", "content": prompt})
        try:
            antwort = self._client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": nachrichten,
                    "stream": False,
                    "options": {"temperature": self.temperature},
                },
            )
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
