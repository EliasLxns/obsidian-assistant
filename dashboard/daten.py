"""Daten von der API holen, kurz zwischengespeichert, damit nicht jeder Klick neu fragt."""

from __future__ import annotations

import streamlit as st

from api_client import ApiClient, Inbox, Status, Vault


@st.cache_resource
def api() -> ApiClient:
    return ApiClient()


@st.cache_data(ttl=20, show_spinner=False)
def status() -> Status:
    return api().status()


@st.cache_data(ttl=20, show_spinner=False)
def inbox() -> Inbox:
    return api().inbox()


@st.cache_data(ttl=60, show_spinner=False)
def vault() -> Vault:
    return api().vault()


def neu_laden() -> None:
    """Nach einer Änderung (Pause, Neu einlesen) alles frisch holen."""
    status.clear()
    inbox.clear()
    vault.clear()
