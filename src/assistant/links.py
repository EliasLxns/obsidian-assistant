"""``obsidian://``-Links, die eine Notiz direkt in Obsidian öffnen."""

from __future__ import annotations

from urllib.parse import quote


def obsidian_url(vault_name: str, path: str) -> str:
    """Link zu einer Notiz, ``path`` relativ zum Vault (mit oder ohne ``.md``).

    >>> obsidian_url("MeinVault", "03 Wissen/Docker/Compose.md")
    'obsidian://open?vault=MeinVault&file=03%20Wissen%2FDocker%2FCompose'
    """
    datei = path.removesuffix(".md")
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(datei, safe='')}"
