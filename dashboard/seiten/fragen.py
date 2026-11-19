"""Fragen an den Vault: Antwort als Lesespalte, Quellen als [[Wikilink]]-Chips."""

from __future__ import annotations

from typing import Any

import streamlit as st

from ansicht import anzahl, art_farbe, art_text, md_escape, notizname, wikilink_chip, zaehler_text
from api_client import ApiFehler, Quelle
from daten import api, inbox, vault


def _fehler_zeigen(e: ApiFehler) -> None:
    if e.status == 409:
        st.info("Der Index ist noch leer. Unter **System** auf „Neu einlesen“ klicken.")
    elif e.status == 503:
        st.warning(f"{e.meldung}", icon=":material/bedtime:")
    else:
        st.error(e.meldung, icon=":material/error:")


def _quellen(quellen: list[Quelle], mit_auszug: bool) -> None:
    for q in quellen:
        kopf = f"**{q['nr']}**&nbsp;&nbsp;{wikilink_chip(notizname(q['pfad']), q['link'])}"
        if q["ueberschrift"]:
            kopf += f"&nbsp;&nbsp;{md_escape(q['ueberschrift'])}"
        zeilen = [kopf, f":gray[`{q['pfad']}`]"]
        if mit_auszug:
            zeilen.append(f":gray[{md_escape(q['auszug'])}]")
        st.markdown("  \n".join(zeilen))


def _ergebnis(e: dict[str, Any]) -> None:
    if "fehler" in e:
        _fehler_zeigen(e["fehler"])
        return
    quellen: list[Quelle] = e["quellen"]
    st.header(e["frage"], anchor=False)
    if e.get("antwort") is not None:
        st.markdown(e["antwort"])
        st.caption(
            f"Formuliert von {e['modell']} in {e['dauer_s']:.1f} s aus "
            f"{anzahl(len(quellen), 'Notiz', 'Notizen')}. "
            "Prüf die Stellen selbst, bevor du dich darauf verlässt."
        )
    if not quellen:
        st.info("Dazu steht nichts im Vault.")
        return
    st.subheader("Quellen", anchor=False)
    _quellen(quellen, mit_auszug=e.get("antwort") is None)


def _seitenleiste() -> None:
    st.subheader("Inbox, letzte Nacht", anchor=False)
    try:
        i = inbox()
    except ApiFehler as e:
        st.caption(e.meldung)
        return
    echte = [lauf for lauf in i["laeufe"] if not lauf["probelauf"]]
    if not echte:
        st.caption("Der Nachtjob ist noch nicht gelaufen.")
    else:
        lauf = echte[0]
        st.caption(f"Lauf {lauf['id']}: {zaehler_text(lauf['zaehler'])}")
        for a in lauf["aktionen"][:6]:
            name = notizname(a["quelle"])
            titel = wikilink_chip(name, a["link"]) if a["link"] else md_escape(name)
            st.markdown(f":{art_farbe(a['art'])}-badge[{art_text(a['art'])}] {titel}")
    offen = len(i["offen"]) + len(i["pruefen"])
    if offen:
        st.caption(f"{anzahl(offen, 'Notiz wartet', 'Notizen warten')} in der Inbox.")

    st.subheader("Vault", anchor=False)
    try:
        v = vault()
    except ApiFehler as e:
        st.caption(e.meldung)
        return
    st.markdown(
        f"{anzahl(v['notizen'], 'Notiz', 'Notizen')} in "
        f"{anzahl(len(v['ordner']), 'Ordner', 'Ordnern')}, "
        f"{anzahl(v['links'], 'Link', 'Links')}"
    )


links, rechts = st.columns([2.2, 1], gap="large")
with links:
    with st.form("frage_form", border=False):
        frage = st.text_input(
            "Frage an deinen Vault", placeholder="Welchen Port nutzt Ollama?", key="frage"
        )
        nur_suchen = st.checkbox("Nur suchen, ohne Antwort zu formulieren", key="nur_suchen")
        los = st.form_submit_button("Fragen", type="primary", icon=":material/search:")
    if los and frage.strip():
        text = frage.strip()
        hinweis = "Suche im Vault …" if nur_suchen else "Formuliere die Antwort …"
        with st.spinner(hinweis, show_time=True):
            try:
                if nur_suchen:
                    ergebnis: dict[str, Any] = {"frage": text, "quellen": api().suchen(text)}
                else:
                    a = api().fragen(text)
                    ergebnis = {"frage": text, **a}
            except ApiFehler as e:
                ergebnis = {"fehler": e}
        st.session_state["ergebnis"] = ergebnis
    if "ergebnis" in st.session_state:
        _ergebnis(st.session_state["ergebnis"])
with rechts:
    _seitenleiste()
