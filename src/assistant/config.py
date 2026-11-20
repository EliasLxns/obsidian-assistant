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

# Wie in retrieval/search.py (dort als Literal); hier ohne Import, damit config schlank bleibt.
SUCHMODI = ("vektor", "bm25", "hybrid")


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
    chroma_host: str = ""  # leer: lokale Chroma-Datei unter chroma_path, sonst HTTP (Docker)
    chroma_port: int = 8000
    suchmodus: str = "hybrid"  # vektor | bm25 | hybrid (für /ask, /search, ask)
    watch_polling: bool = False  # Watcher fragt ab statt inotify (Docker Desktop unter Windows)
    # Nachtjob (Phase 3)
    inbox_dir: str = "00 Inbox"
    nightly_time: str = "03:00"  # Startzeit im Dienstbetrieb
    nightly_window: str = "01:00-06:00"  # außerhalb läuft der Nachtjob nur mit --jetzt
    nightly_state_path: Path = Path(".nachtjob")  # Läufe für Rückgängig, Pause-Schalter
    nightly_skip_if_awake: bool = False  # Gaming-Schutz: nicht laufen, wenn der PC schon wach war
    gaming_pc_mac: str = ""  # leer: kein Wake-on-LAN
    wol_broadcast: str = "255.255.255.255"
    wol_wait_s: float = 180.0
    # Ausschalten per SSH nach getaner Arbeit (nur wenn der Nachtjob geweckt hat)
    gaming_pc_ssh: str = ""  # leer: nie ausschalten; sonst z. B. benutzer@host.docker.internal
    gaming_pc_ssh_key: Path = Path("secrets/gaming_pc_ed25519")
    shutdown_ruhe_min: float = 15.0
    shutdown_max_warten_min: float = 120.0


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


def _ja(wert: str) -> bool:
    return wert.strip().lower() in {"1", "true", "ja", "yes"}


def load_settings(
    env_file: Path = Path(".env"), environ: Mapping[str, str] | None = None
) -> Settings:
    werte = read_env_file(env_file)
    werte.update(os.environ if environ is None else environ)
    d = Settings()

    def get(name: str, default: str) -> str:
        return werte.get(name) or default

    modus = get("SEARCH_MODE", d.suchmodus).strip().lower()
    if modus not in SUCHMODI:
        raise ValueError(f"SEARCH_MODE={modus!r} ist ungültig, erlaubt: {', '.join(SUCHMODI)}")

    return Settings(
        ollama_url=get("OLLAMA_URL", d.ollama_url).rstrip("/"),
        embed_model=get("EMBED_MODEL", d.embed_model),
        chat_model=get("CHAT_MODEL", d.chat_model),
        vault_path=Path(get("VAULT_PATH", str(d.vault_path))),
        vault_name=get("VAULT_NAME", d.vault_name),
        chroma_path=Path(get("CHROMA_PATH", str(d.chroma_path))),
        cache_path=Path(get("EMBED_CACHE_PATH", str(d.cache_path))),
        timeout_s=float(get("OLLAMA_TIMEOUT", str(d.timeout_s))),
        chroma_host=get("CHROMA_HOST", d.chroma_host),
        chroma_port=int(get("CHROMA_PORT", str(d.chroma_port))),
        suchmodus=modus,
        watch_polling=_ja(get("WATCH_POLLING", "")),
        inbox_dir=get("INBOX_DIR", d.inbox_dir),
        nightly_time=get("NIGHTLY_TIME", d.nightly_time),
        nightly_window=get("NIGHTLY_WINDOW", d.nightly_window),
        nightly_state_path=Path(get("NIGHTLY_STATE_PATH", str(d.nightly_state_path))),
        nightly_skip_if_awake=_ja(get("NIGHTLY_SKIP_IF_AWAKE", "")),
        gaming_pc_mac=get("GAMING_PC_MAC", d.gaming_pc_mac),
        wol_broadcast=get("WOL_BROADCAST", d.wol_broadcast),
        wol_wait_s=float(get("WOL_WAIT_S", str(d.wol_wait_s))),
        gaming_pc_ssh=get("GAMING_PC_SSH", d.gaming_pc_ssh),
        gaming_pc_ssh_key=Path(get("GAMING_PC_SSH_KEY", str(d.gaming_pc_ssh_key))),
        shutdown_ruhe_min=float(get("SHUTDOWN_RUHE_MIN", str(d.shutdown_ruhe_min))),
        shutdown_max_warten_min=float(
            get("SHUTDOWN_MAX_WARTEN_MIN", str(d.shutdown_max_warten_min))
        ),
    )
