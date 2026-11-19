"""Wiederkehrende Bausteine der Seiten."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import streamlit as st


def tabelle(
    zeilen: Sequence[Mapping[str, object]], *, link_spalte: str | None = "Obsidian"
) -> None:
    """Kompakte Tabelle ohne Index. ``link_spalte`` hält ``obsidian://``-Links, Anzeige „Öffnen“."""
    config = (
        {link_spalte: st.column_config.LinkColumn(link_spalte, display_text="Öffnen")}
        if link_spalte
        else None
    )
    # Streamlits Typen hängen an pandas, das ohne Stubs „unknown“ ist.
    st.dataframe(  # pyright: ignore[reportUnknownMemberType]
        list(zeilen), column_config=config, hide_index=True, width="stretch"
    )


def balken(namen: Sequence[str], werte: Sequence[int], *, x: str, y: str) -> None:
    """Liegende Balken in der Reihenfolge der Daten (die API sortiert schon)."""
    st.bar_chart(  # pyright: ignore[reportUnknownMemberType]
        {x: list(namen), y: list(werte)},
        x=x,
        y=y,
        horizontal=True,
        sort=False,
        height=40 + 30 * len(namen),
    )
