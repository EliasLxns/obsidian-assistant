"""Git als Sicherheitsnetz: vor und nach jedem Nachtlauf ein Commit im Vault.

So lässt sich jeder Lauf auch ohne den Assistenten mit Git nachvollziehen und zurückdrehen.
Das Repo liegt im Vault (``.git``); Obsidian Sync und der Indexer ignorieren versteckte Ordner.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Eigene Identität, damit kein globales Git-Setup nötig ist. ``safe.directory``: Im Container
# gehört ein eingebundener Ordner oft einem anderen Benutzer, Git würde sonst ablehnen.
_GIT_OPTIONEN = [
    "-c",
    "user.name=Obsidian-Assistent",
    "-c",
    "user.email=nachtjob@localhost",
    "-c",
    "safe.directory=*",
    "-c",
    "core.quotepath=false",
]


class GitError(RuntimeError):
    pass


class VaultGit:
    def __init__(self, vault: Path) -> None:
        self.vault = vault

    def _git(self, *args: str) -> str:
        try:
            ergebnis = subprocess.run(
                ["git", *_GIT_OPTIONEN, *args],
                cwd=self.vault,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
        except FileNotFoundError as e:
            raise GitError("git ist nicht installiert.") from e
        except subprocess.CalledProcessError as e:
            raise GitError(f"git {' '.join(args)} fehlgeschlagen: {e.stderr.strip()}") from e
        return ergebnis.stdout.strip()

    def ist_repo(self) -> bool:
        return (self.vault / ".git").exists()

    def einrichten(self) -> bool:
        """Legt das Repo an, falls es fehlt. Gibt ``True`` zurück, wenn es neu ist."""
        if self.ist_repo():
            return False
        self._git("init", "--quiet")
        return True

    def commit(self, nachricht: str, pfade: list[str] | None = None) -> str | None:
        """Alles committen, oder nur ``pfade`` (relativ zum Vault, auch gelöschte).

        Gibt den Commit-Hash zurück, ``None`` wenn sich nichts geändert hat.
        """
        if pfade is None:
            self._git("add", "--all")
            if not self._git("status", "--porcelain"):
                return None
            self._git("commit", "--quiet", "--no-verify", "-m", nachricht)
        else:
            if not pfade:
                return None
            self._git("add", "--all", "--", *pfade)
            if not self._git("diff", "--cached", "--name-only", "--", *pfade):
                return None
            # Nur diese Pfade: eigene Änderungen anderswo im Vault bleiben außen vor.
            self._git("commit", "--quiet", "--no-verify", "-m", nachricht, "--", *pfade)
        return self._git("rev-parse", "HEAD")
