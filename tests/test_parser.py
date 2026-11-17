from pathlib import Path

from assistant.ingest.parser import iter_notes, parse_file, parse_markdown, split_frontmatter
from tests.conftest import DEMO_VAULT

NOTIZ = """---
tags: [docker, homelab]
erstellt: 2026-03-05
---
# Docker Compose

Einleitung mit #inline-tag und [[Pi-hole]].

## Starten

`docker compose up -d` startet alles. Siehe [[Volumes und Backups|Backups]].

```bash
# Kein Tag und keine Überschrift
echo "#auchkeintag [[KeinLink]]"
```

### Details

Ein Link auf [[Tailscale#Exit Node]] und ein Bild ![[diagramm.png]].
Keine Tags: `#code`, Farbe #123, URL https://x.de/#anker.

## Ende

Fertig. #docker
"""


def test_frontmatter_wird_getrennt() -> None:
    front, rest = split_frontmatter(NOTIZ)
    assert front["tags"] == ["docker", "homelab"]
    assert rest.startswith("# Docker Compose")


def test_ohne_oder_kaputtes_frontmatter() -> None:
    assert split_frontmatter("# Titel\n") == ({}, "# Titel\n")
    front, rest = split_frontmatter("---\n: : [\n---\nText")
    assert front == {}
    assert rest == "Text"


def test_titel_tags_und_links() -> None:
    note = parse_markdown(NOTIZ, "03 Wissen/Docker/Compose.md")
    assert note.title == "Docker Compose"
    assert note.name == "Compose"
    assert note.tags == ("docker", "homelab", "inline-tag")
    assert note.links == ("Pi-hole", "Volumes und Backups", "Tailscale", "diagramm.png")


def test_ueberschriften_bilden_pfade() -> None:
    note = parse_markdown(NOTIZ, "x.md")
    pfade = [s.heading for s in note.sections]
    assert pfade == [
        "Docker Compose",
        "Docker Compose > Starten",
        "Docker Compose > Starten > Details",
        "Docker Compose > Ende",
    ]
    starten = note.sections[1]
    assert starten.level == 2
    assert "# Kein Tag und keine Überschrift" in starten.text  # Codeblock bleibt im Text


def test_text_vor_erster_ueberschrift_und_titel_aus_dateiname() -> None:
    note = parse_markdown("Nur Text ohne Überschrift.\n", "Ordner/Meine Notiz.md")
    assert note.title == "Meine Notiz"
    assert note.sections[0].heading == ""
    assert note.sections[0].text == "Nur Text ohne Überschrift."


def test_tags_als_string_im_frontmatter() -> None:
    note = parse_markdown("---\ntags: garten, tomaten\n---\nText", "a.md")
    assert note.tags == ("garten", "tomaten")


def test_demo_vault_wird_komplett_gelesen() -> None:
    dateien = iter_notes(DEMO_VAULT)
    assert len(dateien) == 25
    assert not any(".obsidian" in p.parts for p in dateien)
    for datei in dateien:
        note = parse_file(datei, DEMO_VAULT)
        assert note.sections, datei
        assert not Path(note.path).is_absolute()
        assert "/" in note.path or note.path.endswith(".md")
