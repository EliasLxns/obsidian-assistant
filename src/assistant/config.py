"""Konfiguration aus ``.env`` und Umgebungsvariablen.

Bewusst ohne ``python-dotenv``: Das Format ist einfach (``SCHLÜSSEL=wert``),
und so bleibt nachvollziehbar, woher jeder Wert kommt. Echte Umgebungsvariablen
haben Vorrang vor der ``.env``-Datei.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    ollama_url: str = "http://localhost:11434"
    embed_model: str = "bge-m3"
    chat_model: str = "qwen2.5:7b-instruct-q4_K_M"
    vault_path: Path = Path("demo_vault")
    vault_name: str = "demo_vault"
    chroma_path: Path = Path(".chroma")
    cache_path: Path = Path(".cache/embeddings.sqlite3")
    timeout_s: float = 120.0


def read_env_file(path: Path) -> dict[str, str]:
    """Liest ``SCHLÜSSEL=wert``-Zeilen. Kommentare und Leerzeilen werden übersprungen."""
    werte: dict[str, str] = {}
    if not path.is_file():
        return werte
    for zeile in path.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, wert = zeile.split("=", 1)
        werte[schluessel.strip()] = wert.strip().strip("\"'")
    return werte


def load_settings(
    env_file: Path = Path(".env"), environ: Mapping[str, str] | None = None
) -> Settings:
    werte = read_env_file(env_file)
    werte.update(os.environ if environ is None else environ)
    d = Settings()

    def get(name: str, default: str) -> str:
        return werte.get(name) or default

    return Settings(
        ollama_url=get("OLLAMA_URL", d.ollama_url).rstrip("/"),
        embed_model=get("EMBED_MODEL", d.embed_model),
        chat_model=get("CHAT_MODEL", d.chat_model),
        vault_path=Path(get("VAULT_PATH", str(d.vault_path))),
        vault_name=get("VAULT_NAME", d.vault_name),
        chroma_path=Path(get("CHROMA_PATH", str(d.chroma_path))),
        cache_path=Path(get("EMBED_CACHE_PATH", str(d.cache_path))),
        timeout_s=float(get("OLLAMA_TIMEOUT", str(d.timeout_s))),
    )
