from pathlib import Path

from assistant.evaluation import (
    EvalQuestion,
    QuestionResult,
    evaluate,
    format_table,
    load_questions,
)
from assistant.index.embedder import FakeEmbedder
from assistant.index.store import InMemoryStore
from assistant.links import obsidian_url
from assistant.llm.answer import KEINE_TREFFER, answer_question
from assistant.llm.client import FakeLLM
from assistant.llm.prompts import SYSTEM_PROMPT
from assistant.retrieval.search import Retriever
from tests.conftest import QUESTIONS


def test_suche_findet_exakten_begriff(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    hits = Retriever(embedder, demo_store).search_notes("Was ist ITBS?", k=3)
    assert hits[0].chunk.path == "03 Wissen/Laufen/Läuferknie.md"
    assert len({h.chunk.path for h in hits}) == len(hits)  # jede Notiz nur einmal


def test_antwort_mit_quellen(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    llm = FakeLLM()
    antwort = answer_question("Welchen Port nutzt Ollama?", Retriever(embedder, demo_store), llm)
    assert antwort.text == llm.answer
    assert len(antwort.sources) == 5
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
    assert len(fragen) == 20
    assert {f.typ for f in fragen} == {"exakt", "umschreibung", "mehrere"}
    assert all(len(f.erwartet) >= 2 for f in fragen if f.typ == "mehrere")


def test_eval_mit_fake_embedder(embedder: FakeEmbedder, demo_store: InMemoryStore) -> None:
    ergebnis = evaluate(Retriever(embedder, demo_store), load_questions(QUESTIONS), k=5)
    # Der FakeEmbedder kennt nur gleiche Wörter: exakte Begriffe muss er trotzdem finden.
    assert ergebnis.rate(5, "exakt") == 1.0
    assert "| **gesamt** | 20 |" in format_table(ergebnis)


def test_eval_set_unbekannter_typ(tmp_path: Path) -> None:
    datei = tmp_path / "q.yaml"
    datei.write_text('- frage: "x"\n  erwartet: "a.md"\n  typ: quatsch\n', encoding="utf-8")
    try:
        load_questions(datei)
    except ValueError as e:
        assert "quatsch" in str(e)
    else:
        raise AssertionError("ValueError erwartet")
