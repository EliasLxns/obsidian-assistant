import itertools

import pytest

from assistant.ingest.chunker import chunk_note, split_text
from assistant.ingest.parser import parse_markdown


def test_kurzer_text_bleibt_ein_stueck() -> None:
    assert split_text("Kurz.", max_chars=100, overlap=10) == ["Kurz."]
    assert split_text("   ", max_chars=100, overlap=10) == []


def test_langer_text_wird_an_absaetzen_geteilt() -> None:
    absaetze = [f"Absatz {i} " + "wort " * 30 for i in range(6)]
    stuecke = split_text("\n\n".join(absaetze), max_chars=400, overlap=50)
    assert len(stuecke) > 1
    assert all(len(s) <= 400 for s in stuecke)
    for i in range(6):  # nichts geht verloren
        assert any(f"Absatz {i}" in s for s in stuecke)


def test_ueberlappung() -> None:
    absaetze = [f"A{i} " + " ".join(f"w{i}x{j}" for j in range(40)) for i in range(4)]
    stuecke = split_text("\n\n".join(absaetze), max_chars=500, overlap=80)
    for vorher, nachher in itertools.pairwise(stuecke):
        letztes_wort = vorher.split()[-1]
        assert letztes_wort in nachher.split()[:20]


def test_ein_riesiger_absatz_wird_hart_geteilt() -> None:
    stuecke = split_text("wort " * 1000, max_chars=300, overlap=30)
    assert all(len(s) <= 300 for s in stuecke)
    assert sum(s.count("wort") for s in stuecke) >= 1000


def test_ungueltige_parameter() -> None:
    with pytest.raises(ValueError):
        split_text("x", max_chars=0, overlap=0)
    with pytest.raises(ValueError):
        split_text("x", max_chars=100, overlap=100)
    with pytest.raises(ValueError):  # würde sonst endlos hart teilen
        split_text("x" * 200, max_chars=100, overlap=99)


def test_chunks_einer_notiz() -> None:
    note = parse_markdown(
        "---\ntags: [a]\n---\n# Titel\n\nIntro [[Andere]].\n\n## Teil\n\n" + "satz. " * 400,
        "Ordner/Notiz.md",
    )
    chunks = chunk_note(note, max_chars=500, overlap=50)
    assert chunks[0].heading == "Titel"
    assert {c.heading for c in chunks[1:]} == {"Titel > Teil"}
    assert [c.id for c in chunks] == [f"Ordner/Notiz.md#{i}" for i in range(len(chunks))]
    assert all(c.tags == ("a",) and c.links == ("Andere",) for c in chunks)
    assert chunks[1].embed_text.startswith("Titel – Titel > Teil\n\n")


def test_hash_aendert_sich_nur_mit_dem_inhalt() -> None:
    a = chunk_note(parse_markdown("# T\n\nText", "n.md"))[0]
    b = chunk_note(parse_markdown("# T\n\nText", "n.md"))[0]
    c = chunk_note(parse_markdown("# T\n\nAnderer Text", "n.md"))[0]
    assert a.hash == b.hash != c.hash
