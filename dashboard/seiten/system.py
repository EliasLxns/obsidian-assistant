"""Systemstatus: API, Ollama auf dem Gaming-PC, Modelle, Index. Neu einlesen per Knopf."""

from __future__ import annotations

import streamlit as st

from ansicht import zeitpunkt
from api_client import ApiFehler
from bausteine import tabelle
from daten import api, neu_laden, status

st.title("System", anchor=False)
try:
    s = status()
except ApiFehler as e:
    st.error(e.meldung, icon=":material/cloud_off:")
    st.caption(f"Erwartet unter `{api().basis_url}` (Umgebungsvariable `API_URL`).")
    st.stop()

with st.container(horizontal=True):
    st.metric("API", "erreichbar", border=True)
    st.metric("Ollama", "wach" if s["ollama_erreichbar"] else "schläft", border=True)
    st.metric("Index", f"{s['chunks']} Abschnitte", border=True)
    st.metric("Version", s["version"], border=True)

st.subheader("Modelle", anchor=False)
tabelle(
    [
        {"Aufgabe": "Antworten und Einsortieren", "Modell": s["chat_modell"]},
        {"Aufgabe": "Embeddings (Suche)", "Modell": s["embed_modell"]},
    ],
    link_spalte=None,
)
if not s["ollama_erreichbar"]:
    st.info(
        "Ollama antwortet nicht. Meist schläft der Gaming-PC. Suchen und Fragen gehen erst, "
        "wenn er wach ist. Der Nachtjob weckt ihn bei Bedarf selbst.",
        icon=":material/bedtime:",
    )

st.subheader("Index", anchor=False)
lauf = s["letzter_indexlauf"]
if lauf:
    st.markdown(
        f"Letzter Lauf {zeitpunkt(lauf['zeitpunkt'])}: {lauf['notes']} Notizen, "
        f"{lauf['chunks']} Abschnitte, davon {lauf['embedded']} neu eingebettet, "
        f"{lauf['deleted']} gelöscht ({lauf['dauer_s']:.1f} s)."
    )
else:
    st.caption(
        "Seit dem Start der API noch kein Lauf über die API. Der Indexer-Dienst hält den "
        "Index trotzdem aktuell."
    )
if st.button(
    "Neu einlesen", icon=":material/refresh:", disabled=not s["ollama_erreichbar"], type="primary"
):
    with st.spinner("Lese den Vault ein …", show_time=True):
        try:
            neu = api().reindex()
        except ApiFehler as e:
            st.error(e.meldung)
        else:
            neu_laden()
            st.success(
                f"{neu['embedded']} Abschnitte neu eingebettet, {neu['unchanged']} unverändert."
            )

st.caption(f"Vault `{s['vault']}` · API `{api().basis_url}`")
