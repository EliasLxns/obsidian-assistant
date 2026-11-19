"""FastAPI-Anwendung: /ask, /search, /status, /reindex, /inbox, /vault, /nachtjob/pause."""

from assistant.api.app import create_app

__all__ = ["create_app"]
