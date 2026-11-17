"""FastAPI-Anwendung: /ask, /search, /status, /reindex."""

from assistant.api.app import create_app

__all__ = ["create_app"]
