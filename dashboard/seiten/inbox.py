"""Inbox: was wartet, was hat der Nachtjob getan, Gaming-Schutz ein- und ausschalten."""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from ansicht import anzahl, art_text, notizname, zaehler_text, zeitpunkt
from api_client import ApiFehler, Lauf, Notiz
from bausteine import tabelle
from daten import api, inbox, neu_laden


def _tabelle(notizen: list[Notiz]) -> None:
    tabelle(
        [
            {
                "Notiz": n["titel"],
                "Stand": art_text(n["art"]),
                "Geändert": zeitpunkt(n["geaendert"]),
                "Obsidian": n["link"],
            }
            for n in notizen
        ],
    )


def _lauf(lauf: Lauf) -> None:
    for h in lauf["hinweise"]:
        st.caption(h)
    if not lauf["aktionen"]:
        return
    tabelle(
        [
            {
                "Was": art_text(a["art"]),
                "Notiz": notizname(a["quelle"]),
                "Wohin": a["ziel"] if a["ziel"] != a["quelle"] else "",
                "Details": a["details"],
                "Obsidian": a["link"],
            }
            for a in lauf["aktionen"]
        ],
    )


def _pause() -> None:
    p = i["pause"]
    with st.container(border=True):
        if p["aktiv"]:
            bis = f"bis {zeitpunkt(p['bis'])}" if p["bis"] else "bis du sie aufhebst"
            grund = f" ({p['grund']})" if p["grund"] else ""
            st.markdown(f"**Gaming-Schutz an:** Der Nachtjob weckt den PC nicht, {bis}{grund}.")
            if st.button("Pause aufheben", icon=":material/play_arrow:"):
                _ausfuehren(lambda: api().pause_aufheben())
            return
        st.markdown(
            "**Gaming-Schutz:** Heute Nacht soll der PC in Ruhe bleiben? "
            "Dann den Nachtjob pausieren."
        )
        with st.form("pause_form", border=False), st.container(horizontal=True):
            dauer = st.selectbox(
                "Dauer",
                ["Bis morgen früh (12 h)", "24 Stunden", "Bis ich sie aufhebe"],
                label_visibility="collapsed",
            )
            if st.form_submit_button("Pausieren", icon=":material/pause:"):
                stunden = {"Bis morgen früh (12 h)": 12.0, "24 Stunden": 24.0}.get(dauer)
                _ausfuehren(lambda: api().pause_setzen(stunden, "über das Dashboard"))


def _ausfuehren(aktion: Callable[[], object]) -> None:
    try:
        aktion()
    except ApiFehler as e:
        st.error(e.meldung)
        return
    neu_laden()
    st.rerun()


st.title("Inbox", anchor=False)
try:
    i = inbox()
except ApiFehler as e:
    st.error(e.meldung)
    st.stop()

arten = [n["art"] for n in i["offen"]]
with st.container(horizontal=True):
    st.metric("Wartet", arten.count("notiz"), border=True)
    st.metric("Offene Fragen", arten.count("frage"), border=True)
    st.metric("Zum Prüfen", len(i["pruefen"]), border=True)
    naechster = zeitpunkt(i["naechster_lauf"]) if i["naechster_lauf"] else "pausiert"
    st.metric("Nächster Lauf", naechster, border=True)

_pause()

st.subheader("In der Inbox", anchor=False)
if i["offen"]:
    st.caption(
        "Neue Notizen sortiert der Nachtjob ein, „Frage:“-Notizen beantwortet er. "
        "Notizen, an denen in der letzten halben Stunde geschrieben wurde, bleiben liegen."
    )
    _tabelle(i["offen"])
else:
    st.caption("Leer. Nichts zu tun für heute Nacht.")

st.subheader("Zum Prüfen", anchor=False)
if i["pruefen"]:
    st.caption(
        "Hier war sich der Nachtjob nicht sicher. Bitte selbst einsortieren, "
        "der Vorschlag steht im Protokoll."
    )
    _tabelle(i["pruefen"])
else:
    st.caption("Nichts offen.")

st.subheader("Letzte Läufe", anchor=False)
if not i["laeufe"]:
    st.caption("Der Nachtjob ist noch nicht gelaufen.")
for nr, lauf in enumerate(i["laeufe"]):
    art = "Probelauf" if lauf["probelauf"] else "Lauf"
    titel = f"{art} {zeitpunkt(lauf['start'])}: {zaehler_text(lauf['zaehler'])}"
    with st.expander(titel, expanded=nr == 0):
        st.caption(f"Gaming-PC: {lauf['pc'] or 'unbekannt'}")
        _lauf(lauf)
        if not lauf["probelauf"] and lauf["aktionen"]:
            st.caption(
                f"Rückgängig auf dem Server: `assistant nightly rueckgaengig {lauf['id']}` "
                f"({anzahl(len(lauf['aktionen']), 'Notiz', 'Notizen')})"
            )
