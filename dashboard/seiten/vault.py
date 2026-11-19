"""Vault-Statistik: Umfang, Ordner, Tags, Pflegehinweise (tote Links, Notizen ohne Links)."""

from __future__ import annotations

import streamlit as st

from ansicht import notizname, zeitpunkt
from api_client import ApiFehler
from bausteine import balken, tabelle
from daten import vault

st.title("Vault", anchor=False)
try:
    v = vault()
except ApiFehler as e:
    st.error(e.meldung)
    st.stop()

with st.container(horizontal=True):
    st.metric("Notizen", v["notizen"], border=True)
    st.metric("Wörter", f"{v['woerter']:,}".replace(",", "."), border=True)
    st.metric("Wikilinks", v["links"], border=True)
    st.metric("Tote Links", v["tote_links_anzahl"], border=True)

links, rechts = st.columns(2, gap="large")
with links:
    st.subheader("Ordner", anchor=False)
    ordner = [o["name"] for o in v["ordner"]]
    balken(ordner, [o["anzahl"] for o in v["ordner"]], x="Ordner", y="Notizen")

with rechts:
    st.subheader("Häufigste Tags", anchor=False)
    if v["tags"]:
        tags = [f"#{t['name']}" for t in v["tags"]]
        balken(tags, [t["anzahl"] for t in v["tags"]], x="Tag", y="Notizen")
    else:
        st.caption("Noch keine Tags.")

st.subheader("Zuletzt geändert", anchor=False)
tabelle(
    [
        {
            "Notiz": n["titel"],
            "Ordner": n["pfad"].rpartition("/")[0],
            "Geändert": zeitpunkt(n["geaendert"]),
            "Obsidian": n["link"],
        }
        for n in v["zuletzt"]
    ],
)

st.subheader("Pflege", anchor=False)
pflege_links, pflege_rechts = st.columns(2, gap="large")
with pflege_links:
    st.markdown(f"**Tote Links** ({v['tote_links_anzahl']})")
    st.caption("Wikilinks auf Notizen, die es (noch) nicht gibt.")
    if v["tote_links"]:
        tabelle(
            [
                {"In": notizname(t["notiz"]), "Zeigt auf": t["ziel"], "Obsidian": t["link"]}
                for t in v["tote_links"]
            ],
        )
with pflege_rechts:
    st.markdown(f"**Ohne Links** ({v['ohne_links_anzahl']})")
    st.caption("Notizen, die weder verlinken noch verlinkt werden.")
    if v["ohne_links"]:
        tabelle(
            [{"Notiz": notizname(p["pfad"]), "Obsidian": p["link"]} for p in v["ohne_links"]],
        )
