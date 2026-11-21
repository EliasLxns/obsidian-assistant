from pathlib import Path

from assistant.evaluation import (
    EvalQuestion,
    EvalResult,
    QuestionResult,
    evaluate,
    format_details,
    format_table,
    load_questions,
)
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import Hit, InMemoryStore
from assistant.ingest.chunker import Chunk
from assistant.links import obsidian_url
from assistant.llm.answer import KEINE_TREFFER, answer_question, nur_zitierte
from assistant.llm.client import FakeLLM
from assistant.llm.prompts import SYSTEM_PROMPT
from assistant.retrieval.search import Retriever
from tests.conftest import QUESTIONS, ROOT


def test_suche_findet_exakten_begriff(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    hits = Retriever(embedder, demo_store).search_notes("Was ist ITBS?", k=3)
    assert hits[0].chunk.path == "03 Wissen/Laufen/Läuferknie.md"
    assert len({h.chunk.path for h in hits}) == len(hits)  # jede Notiz nur einmal


def test_antwort_mit_quellen(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    llm = FakeLLM()
    antwort = answer_question("Welchen Port nutzt Ollama?", Retriever(embedder, demo_store), llm)
    assert antwort.text == llm.answer
    assert len(antwort.sources) == 1  # nur die zitierte Quelle [1]
    system, prompt = llm.prompts[0]
    assert system == SYSTEM_PROMPT
    assert "[1] " in prompt and "Frage: Welchen Port nutzt Ollama?" in prompt
    assert "11434" in prompt  # der passende Chunk steckt im Kontext


def test_leerer_index_fragt_kein_llm() -> None:
    llm = FakeLLM()
    antwort = answer_question("x", Retriever(FakeEmbedder(), InMemoryStore()), llm)
    assert antwort.text == KEINE_TREFFER
    assert llm.prompts == []


def test_obsidian_url() -> None:
    assert (
        obsidian_url("Mein Vault", "03 Wissen/Laufen/Läuferknie.md")
        == "obsidian://open?vault=Mein%20Vault&file=03%20Wissen%2FLaufen%2FL%C3%A4uferknie"
    )


def test_treffer_bei_mehreren_notizen() -> None:
    q = EvalQuestion("f", ("a.md", "b.md"), "mehrere")
    assert QuestionResult(q, ("a.md", "x.md", "b.md")).hit_at(1)
    assert QuestionResult(q, ("a.md", "x.md", "b.md")).hit_at(5)
    assert not QuestionResult(q, ("a.md", "x.md", "y.md")).hit_at(5)
    assert not QuestionResult(q, ("x.md", "a.md", "b.md")).hit_at(1)
    assert QuestionResult(q, ("x.md", "b.md")).rank() == 2


def test_eval_set_laden() -> None:
    fragen = load_questions(QUESTIONS)
    assert len(fragen) == 23
    assert {f.typ for f in fragen} == {"exakt", "umschreibung", "mehrere", "verlinkt"}
    assert all(len(f.erwartet) >= 2 for f in fragen if f.typ in {"mehrere", "verlinkt"})


def test_eval_mit_fake_embedder(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    ergebnis = evaluate(Retriever(embedder, demo_store), load_questions(QUESTIONS), k=5)
    # Der FakeEmbedder kennt nur gleiche Wörter: exakte Begriffe muss er trotzdem finden.
    assert ergebnis.rate(5, "exakt") == 1.0
    assert "| **gesamt** | 23 |" in format_table(ergebnis)


def test_eval_set_unbekannter_typ(tmp_path: Path) -> None:
    datei = tmp_path / "q.yaml"
    datei.write_text('- frage: "x"\n  erwartet: "a.md"\n  typ: quatsch\n', encoding="utf-8")
    try:
        load_questions(datei)
    except ValueError as e:
        assert "quatsch" in str(e)
    else:
        raise AssertionError("ValueError erwartet")


def _hits(*pfade: str) -> list[Hit]:
    return [Hit(Chunk(f"{p}#0", p, p, "", "text"), 1.0) for p in pfade]


def test_nur_zitierte_quellen_neu_nummeriert() -> None:
    hits = _hits("a.md", "b.md", "c.md", "d.md")
    text, quellen = nur_zitierte("Erst C [3]. Dann A [1][3]. Code `werte[0]`, Jahr [2026].", hits)
    assert text == "Erst C [1]. Dann A [2][1]. Code `werte[0]`, Jahr [2026]."
    assert [h.chunk.path for h in quellen] == ["c.md", "a.md"]


def test_nur_zitierte_mit_komma_und_bereich() -> None:
    hits = _hits("a.md", "b.md", "c.md", "d.md")
    text, quellen = nur_zitierte("Port [2, 4]. Dienst [1–2].", hits)
    assert text == "Port [1][2]. Dienst [3][1]."
    assert [h.chunk.path for h in quellen] == ["b.md", "d.md", "a.md"]


def test_ohne_zitate_bleiben_alle_quellen() -> None:
    hits = _hits("a.md", "b.md")
    assert nur_zitierte("Keine Nummern.", hits) == ("Keine Nummern.", hits)


def test_prompt_verlangt_du_und_nichts_erfinden() -> None:
    assert "„du“" in SYSTEM_PROMPT and "Erfinde keine" in SYSTEM_PROMPT


def test_eval_set_ohne_antwort_laden(tmp_path: Path) -> None:
    datei = tmp_path / "q.yaml"
    datei.write_text(
        '- frage: "a"\n  typ: ohne_antwort\n- frage: "b"\n  erwartet: []\n  typ: ohne_antwort\n',
        encoding="utf-8",
    )
    fragen = load_questions(datei)
    assert [f.erwartet for f in fragen] == [(), ()]
    assert not any(f.beantwortbar for f in fragen)


def test_eval_set_ohne_antwort_mit_erwartet_ist_fehler(tmp_path: Path) -> None:
    datei = tmp_path / "q.yaml"
    for inhalt in (
        '- frage: "a"\n  erwartet: "x.md"\n  typ: ohne_antwort\n',
        '- frage: "a"\n  typ: exakt\n',
    ):
        datei.write_text(inhalt, encoding="utf-8")
        try:
            load_questions(datei)
        except ValueError as e:
            assert "erwartet" in str(e)
        else:
            raise AssertionError("ValueError erwartet")


def _gemischt() -> EvalResult:
    mit = EvalQuestion("mit", ("a.md",), "exakt")
    ohne = EvalQuestion("ohne", (), "ohne_antwort")
    return EvalResult(
        [
            QuestionResult(mit, ("a.md", "b.md"), (0.7, 0.4)),
            QuestionResult(ohne, ("b.md",), (0.45,)),
            QuestionResult(ohne, (), ()),
        ],
        k=5,
    )


def test_ohne_antwort_zaehlt_nicht_in_treffer() -> None:
    ergebnis = _gemischt()
    assert ergebnis.rate(5) == 1.0  # nur die eine beantwortbare Frage
    assert ergebnis.unter_schwelle(0.5, beantwortbar=False) == (2, 2)  # ohne Treffer zählt mit
    assert ergebnis.unter_schwelle(0.5, beantwortbar=True) == (0, 1)
    assert ergebnis.unter_schwelle(0.8, beantwortbar=True) == (1, 1)


def test_tabelle_mit_ohne_antwort_und_schwelle() -> None:
    tabelle = format_table(_gemischt(), schwelle=0.5)
    assert "| ohne_antwort | 2 | – | – |" in tabelle
    assert "| **gesamt** | 1 |" in tabelle
    assert "| mit Antwort | 1 | 0.700 | 0.700 | 0.700 |" in tabelle
    assert "| ohne Antwort | 2 | 0.450 | 0.450 | 0.450 |" in tabelle
    assert "2 von 2 Fragen ohne Antwort abgelehnt, 0 von 1" in tabelle
    assert "| ohne | ohne_antwort | – | – | – |" in format_details(_gemischt())


def test_tabelle_ohne_fragen_ohne_antwort_bleibt_kurz() -> None:
    q = EvalQuestion("f", ("a.md",), "exakt")
    assert "Bester Score" not in format_table(EvalResult([QuestionResult(q, ("a.md",))], k=5))


def test_schweres_set_mit_fake_embedder(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    fragen = load_questions(ROOT / "eval" / "schwer.yaml")
    ergebnis = evaluate(Retriever(embedder, demo_store), fragen, k=5)
    assert len(ergebnis.beantwortbar) == 23 and len(ergebnis.ohne_antwort) == 7
    assert all(r.scores for r in ergebnis.beantwortbar)
