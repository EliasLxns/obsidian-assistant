"""Dashboard des Obsidian-Assistenten: Fragen, Inbox, Vault, System.

Start: ``cd dashboard && streamlit run app.py`` (die API muss laufen, Adresse in ``API_URL``).
Das Aussehen steht nur in ``.streamlit/config.toml`` (Design „Graphit & Moos“).
"""

from __future__ import annotations

import streamlit as st

from ansicht import zeitpunkt
from api_client import ApiFehler
from daten import inbox, status

st.set_page_config(page_title="Obsidian-Assistent", page_icon=":material/forum:", layout="wide")


def kopfzeile() -> None:
    """Drei Lämpchen wie im Entwurf: Gaming-PC, Index, Nachtjob."""
    try:
        s = status()
    except ApiFehler as e:
        st.badge("API nicht erreichbar", icon=":material/cloud_off:", color="red")
        st.caption(e.meldung)
        return
    with st.container(horizontal=True, gap="small"):
        if s["ollama_erreichbar"]:
            st.badge("Gaming-PC wach", icon=":material/bolt:", color="green")
        else:
            st.badge("Gaming-PC schläft", icon=":material/bedtime:", color="gray")
        if s["chunks"]:
            st.badge(f"Index: {s['chunks']} Abschnitte", icon=":material/database:", color="green")
        else:
            st.badge("Index leer", icon=":material/database:", color="orange")
        try:
            i = inbox()
        except ApiFehler:
            return
        if i["pause"]["aktiv"]:
            bis = f" bis {zeitpunkt(i['pause']['bis'])}" if i["pause"]["bis"] else ""
            st.badge(f"Nachtjob pausiert{bis}", icon=":material/pause:", color="orange")
        else:
            text = f"Nachtjob {zeitpunkt(i['naechster_lauf'])}"
            st.badge(text, icon=":material/schedule:", color="gray")


seiten = st.navigation(
    [
        st.Page("seiten/fragen.py", title="Fragen", icon=":material/search:", default=True),
        st.Page("seiten/inbox.py", title="Inbox", icon=":material/inbox:"),
        st.Page("seiten/vault.py", title="Vault", icon=":material/folder:"),
        st.Page("seiten/system.py", title="System", icon=":material/monitor_heart:"),
    ],
    position="top",
)
kopfzeile()
seiten.run()
