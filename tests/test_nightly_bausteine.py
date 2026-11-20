"""Bausteine des Nachtjobs: Wake-on-LAN, Gaming-Schutz, Inbox-Entscheidungen."""

from collections import Counter
from datetime import datetime, time, timedelta
from pathlib import Path

import httpx
import pytest

from assistant.index.store import Hit
from assistant.ingest.chunker import Chunk
from assistant.ingest.parser import parse_markdown, split_frontmatter
from assistant.llm.client import OllamaLLM, unload_models
from assistant.nightly.guard import (
    aktive_pause,
    im_fenster,
    parse_fenster,
    pause_aufheben,
    pause_setzen,
    sekunden_bis,
    warum_nicht,
)
from assistant.nightly.inbox import (
    SORT_SYSTEM,
    Entscheidung,
    build_sort_prompt,
    inbox_notes,
    ist_frage,
    mit_thema,
    notiz_ergaenzen,
    ordner_themen,
    parse_entscheidung,
    verwandte_notizen,
    vorhandene_tags,
    wikilink,
    zielordner,
)
from assistant.nightly.questions import frage_aus_notiz
from assistant.nightly.wol import FakeWaker, magic_packet, wake_and_wait
from tests.conftest import DEMO_VAULT

# --- Wake-on-LAN -------------------------------------------------------------


@pytest.mark.parametrize("mac", ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AABBCCDDEEFF"])
def test_magic_packet(mac: str) -> None:
    paket = magic_packet(mac)
    assert len(paket) == 102
    assert paket[:6] == b"\xff" * 6
    assert paket[6:] == bytes.fromhex("AABBCCDDEEFF") * 16


@pytest.mark.parametrize("mac", ["", "AA:BB:CC:DD:EE", "AA:BB-CC:DD:EE:FF", "GG:BB:CC:DD:EE:FF"])
def test_magic_packet_lehnt_unsinn_ab(mac: str) -> None:
    with pytest.raises(ValueError):
        magic_packet(mac)


class Uhr:
    """Simulierte Zeit: ``sleep`` dreht nur die Uhr weiter."""

    def __init__(self) -> None:
        self.t = 0.0

    def clock(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_wach_wird_nicht_geweckt() -> None:
    waker = FakeWaker()
    r = wake_and_wait(lambda: True, waker)
    assert r.war_wach and r.erreichbar and waker.gesendet == 0


def test_wecken_und_warten() -> None:
    uhr, waker = Uhr(), FakeWaker()
    r = wake_and_wait(
        lambda: uhr.t >= 40, waker, timeout_s=180, intervall_s=5, sleep=uhr.sleep, clock=uhr.clock
    )
    assert not r.war_wach and r.erreichbar
    assert waker.gesendet == 1
    assert r.wartezeit_s == 40


def test_wecken_wiederholt_paket_und_gibt_auf() -> None:
    uhr, waker = Uhr(), FakeWaker()
    r = wake_and_wait(
        lambda: False,
        waker,
        timeout_s=180,
        intervall_s=5,
        erneut_senden_s=60,
        sleep=uhr.sleep,
        clock=uhr.clock,
    )
    assert not r.erreichbar
    assert waker.gesendet == 3  # bei 0, 60 und 120 s


def test_ohne_mac_wird_nur_geprueft() -> None:
    r = wake_and_wait(lambda: False, None)
    assert not r.erreichbar and r.gesendet == 0


def test_modelle_entladen() -> None:
    gesehen: list[tuple[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        import json

        daten = json.loads(req.content)
        gesehen.append((req.url.path, daten["model"]))
        # Embedding-Modell kennt /api/generate nicht
        if req.url.path == "/api/generate" and daten["model"] == "bge-m3":
            return httpx.Response(400)
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fehler = unload_models("http://ollama:11434", ["qwen", "bge-m3"], client=client)
    assert fehler == []
    assert gesehen == [
        ("/api/generate", "qwen"),
        ("/api/generate", "bge-m3"),
        ("/api/embed", "bge-m3"),
    ]


def test_ollama_json_modus() -> None:
    anfragen: list[bytes] = []

    def handler(req: httpx.Request) -> httpx.Response:
        anfragen.append(req.content)
        return httpx.Response(200, json={"message": {"content": "{}"}})

    llm = OllamaLLM("http://o", "m", client=httpx.Client(transport=httpx.MockTransport(handler)))
    llm.generate("a")
    llm.generate("b", json=True)
    assert b'"format"' not in anfragen[0]
    assert b'"format":"json"' in anfragen[1].replace(b" ", b"")


# --- Gaming-Schutz -------------------------------------------------------------


def test_zeitfenster() -> None:
    nacht = parse_fenster("01:00-06:00")
    assert im_fenster(datetime(2026, 11, 18, 3, 0), nacht)
    assert not im_fenster(datetime(2026, 11, 18, 6, 0), nacht)
    assert not im_fenster(datetime(2026, 11, 17, 22, 0), nacht)
    ueber_mitternacht = parse_fenster("23:00-05:00")
    assert im_fenster(datetime(2026, 11, 17, 23, 30), ueber_mitternacht)
    assert im_fenster(datetime(2026, 11, 18, 4, 0), ueber_mitternacht)
    assert not im_fenster(datetime(2026, 11, 18, 12, 0), ueber_mitternacht)


@pytest.mark.parametrize("text", ["3 Uhr", "01:00", "25:00-06:00"])
def test_zeitfenster_fehler(text: str) -> None:
    with pytest.raises(ValueError):
        parse_fenster(text)


def test_sekunden_bis() -> None:
    assert sekunden_bis(datetime(2026, 11, 17, 23, 0), time(3, 0)) == 4 * 3600
    assert sekunden_bis(datetime(2026, 11, 18, 3, 0), time(3, 0)) == 24 * 3600


def test_pause(tmp_path: Path) -> None:
    jetzt = datetime(2026, 11, 17, 22, 0)
    fenster = parse_fenster("00:00-23:59")
    assert warum_nicht(tmp_path, jetzt, fenster) is None

    pause_setzen(tmp_path, jetzt + timedelta(hours=8), "LAN-Party")
    grund = warum_nicht(tmp_path, jetzt, fenster)
    assert grund is not None and "LAN-Party" in grund
    assert aktive_pause(tmp_path, jetzt + timedelta(hours=9)) is None  # abgelaufen

    pause_setzen(tmp_path, None)
    assert aktive_pause(tmp_path, jetzt + timedelta(days=30)) is not None
    assert pause_aufheben(tmp_path)
    assert not pause_aufheben(tmp_path)


def test_kaputte_pause_datei_pausiert_sicherheitshalber(tmp_path: Path) -> None:
    (tmp_path / "pause.json").write_text("{kaputt", encoding="utf-8")
    assert aktive_pause(tmp_path, datetime(2026, 11, 18, 3, 0)) is not None


def test_ausserhalb_des_fensters(tmp_path: Path) -> None:
    grund = warum_nicht(tmp_path, datetime(2026, 11, 17, 22, 0), parse_fenster("01:00-06:00"))
    assert grund is not None and "--jetzt" in grund


# --- Inbox ---------------------------------------------------------------------

ORDNER = ["03 Wissen/Garten", "03 Wissen/Homelab"]


def test_entscheidung_gueltig() -> None:
    e = parse_entscheidung(
        'Hier: {"ordner": "03 Wissen/Garten", "tags": ["#Garten", "Hoch Beet", "garten"],'
        ' "sicher": true, "grund": "Hochbeet"}',
        ORDNER,
    )
    assert e.ordner == "03 Wissen/Garten" and e.sicher
    assert e.tags == ("garten", "hoch-beet")


@pytest.mark.parametrize(
    "roh",
    [
        "kein json",
        "[1, 2]",
        '{"ordner": "99 Erfunden", "tags": [], "sicher": true}',
        '{"ordner": null, "tags": ["x"], "sicher": true}',
        '{"ordner": "03 Wissen/Garten", "sicher": "ja"}',
    ],
)
def test_entscheidung_unsicher(roh: str) -> None:
    assert not parse_entscheidung(roh, ORDNER).sicher


def test_zielordner_ohne_inbox() -> None:
    ordner = zielordner(DEMO_VAULT, "00 Inbox")
    assert "03 Wissen/Garten" in ordner
    assert not any(o.startswith("00 Inbox") for o in ordner)
    assert all(1 <= len(b) <= 4 for b in ordner.values())


def test_notiz_ergaenzen_behaelt_frontmatter() -> None:
    text = "---\ntags: [idee]\nerstellt: 2026-11-15\n---\n# Titel\n\nText #inline\n"
    neu = notiz_ergaenzen(text, ["garten", "idee"], ["[[Hochbeet anlegen]]"])
    fm, body = split_frontmatter(neu)
    assert fm["tags"] == ["idee", "garten"]
    assert str(fm["erstellt"]) == "2026-11-15"
    assert body.startswith("# Titel\n\nText #inline")
    assert body.endswith("## Verwandt\n\n- [[Hochbeet anlegen]]\n")
    # Zweimal ergänzen verdoppelt nichts
    assert notiz_ergaenzen(neu, ["garten"], ["[[Hochbeet anlegen]]"]) == neu


def test_frontmatter_bleibt_zeichengenau() -> None:
    text = "---\nerstellt: 2026-11-15 10:30  # am Handy\ntags:\n  - idee\nquelle: 'x'\n---\n# T\n"
    neu = notiz_ergaenzen(text, ["garten"], [])
    assert neu == text.replace("tags:\n  - idee\n", "tags: [idee, garten]\n")


def test_ungueltiges_frontmatter_bleibt_unangetastet() -> None:
    text = "---\nerstellt: {{date}}\nquelle: a: b\n---\n# T\n"
    neu = notiz_ergaenzen(text, ["garten"], ["[[A]]"])
    assert neu == text + "\n## Verwandt\n\n- [[A]]\n"


def test_notiz_ohne_frontmatter_bekommt_eins() -> None:
    neu = notiz_ergaenzen("# Idee\n\nText\n", ["garten"], [])
    assert neu.startswith("---\ntags: [garten]\n---\n# Idee")


def test_wikilink_bei_doppelten_namen() -> None:
    namen = Counter({"Compose": 1, "Notizen": 2})
    assert wikilink("03 Wissen/Docker/Compose.md", namen) == "[[Compose]]"
    assert wikilink("a/Notizen.md", namen) == "[[a/Notizen]]"


def test_frische_notizen_bleiben_liegen(tmp_path: Path) -> None:
    (tmp_path / "00 Inbox" / "Prüfen").mkdir(parents=True)
    neu = tmp_path / "00 Inbox" / "neu.md"
    neu.write_text("# neu", encoding="utf-8")
    (tmp_path / "00 Inbox" / "Prüfen" / "alt.md").write_text("# alt", encoding="utf-8")
    jetzt = datetime.now()
    assert inbox_notes(tmp_path, "00 Inbox", jetzt) == []
    assert inbox_notes(tmp_path, "00 Inbox", jetzt + timedelta(hours=1)) == [neu]


def test_frage_erkennen() -> None:
    text = (DEMO_VAULT / "00 Inbox" / "Frage Gel beim Halbmarathon.md").read_text(encoding="utf-8")
    note = parse_markdown(text, "00 Inbox/Frage Gel beim Halbmarathon.md")
    assert ist_frage(note)
    frage = frage_aus_notiz(note, text)
    assert frage.startswith("Wann sollte ich beim Halbmarathon ein Gel nehmen?")
    assert "Laufzeit" in frage
    idee = parse_markdown("# Gedanke: Sensor\n\nText", "00 Inbox/Idee.md")
    assert not ist_frage(idee)


class _FesteTreffer:
    """Retriever-Attrappe mit festen Scores."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def search_notes(self, query: str, k: int = 5) -> list[Hit]:
        return [Hit(Chunk(f"{p}#0", p, p, "", "x"), s) for p, s in self.scores.items()][:k]


def test_verwandte_notizen_nur_nah_am_besten() -> None:
    """Werte wie im Probelauf mit bge-m3: fremde Notizen ~0,44, passende 0,53 bis 0,71."""
    r = _FesteTreffer(
        {
            "00 Inbox/Andere.md": 0.9,
            "Compose.md": 0.71,
            "Docker.md": 0.64,
            "Pi-hole.md": 0.58,
            "Trainingsplan.md": 0.44,
        }
    )
    treffer = verwandte_notizen(r, "text", "00 Inbox")  # type: ignore[arg-type]
    assert [h.chunk.path for h in treffer] == ["Compose.md", "Docker.md"]  # Pi-hole: 0,13 hinter
    nichts = _FesteTreffer({"Trainingsplan.md": 0.44})
    assert verwandte_notizen(nichts, "text", "00 Inbox") == []  # type: ignore[arg-type]


def test_vorhandene_tags_fuer_den_prompt() -> None:
    tags = vorhandene_tags(DEMO_VAULT, "00 Inbox")
    assert tags and all(t == t.lower() for t in tags)
    note = parse_markdown("# Neu\n\nText", "00 Inbox/Neu.md")
    prompt = build_sort_prompt(note, "# Neu\n\nText", {"03 Wissen/Garten": ["Tomaten"]}, [], tags)
    assert f"Vorhandene Tags: {tags[0]}" in prompt
    assert "ä, ö, ü" in SORT_SYSTEM


def test_thema_des_zielordners_kommt_dazu() -> None:
    themen = ordner_themen(DEMO_VAULT, "00 Inbox")
    assert themen["03 Wissen/Garten"] == "garten"
    e = Entscheidung("03 Wissen/Garten", ("hochbeet", "sensor"), True, "")
    assert mit_thema(e, themen).tags == ("garten", "hochbeet", "sensor")
    assert mit_thema(Entscheidung("03 Wissen/Garten", ("garten",), True, ""), themen).tags == (
        "garten",
    )
    voll = Entscheidung("03 Wissen/Garten", ("a", "b", "c", "d"), True, "")
    assert mit_thema(voll, themen).tags == ("garten", "a", "b", "c")  # höchstens 4
    assert mit_thema(Entscheidung(None, ("a",), False, ""), themen).tags == ("a",)
