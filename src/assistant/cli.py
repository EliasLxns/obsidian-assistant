"""Kommandozeile: ``assistant index | ask | eval``.

Die Bausteine (Embedder, VectorStore, LLM) kommen aus einer ``Components``-Fabrik.
Im Normalbetrieb sind das Ollama und ChromaDB, in Tests Fakes.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from assistant.config import Settings, load_settings
from assistant.evaluation import evaluate, format_details, format_table, load_questions
from assistant.index.embedder import Embedder, EmbeddingCache, OllamaEmbedder, OllamaError
from assistant.index.store import ChromaStore, InMemoryStore, VectorStore
from assistant.ingest.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP
from assistant.ingest.indexer import index_vault
from assistant.links import obsidian_url
from assistant.llm.answer import answer_question
from assistant.llm.client import LLM, OllamaLLM
from assistant.retrieval.search import Retriever


@dataclass
class Components:
    settings: Settings
    embedder: Embedder
    store: VectorStore
    llm: LLM


ComponentsFactory = Callable[[Settings], Components]


def default_components(settings: Settings) -> Components:
    cache = EmbeddingCache(settings.cache_path)
    return Components(
        settings=settings,
        embedder=OllamaEmbedder.for_model(
            settings.ollama_url, settings.embed_model, cache=cache, timeout_s=settings.timeout_s
        ),
        store=ChromaStore(settings.chroma_path),
        llm=OllamaLLM(settings.ollama_url, settings.chat_model, timeout_s=settings.timeout_s),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="assistant",
        description="Lokaler RAG-Assistent für einen Obsidian-Vault.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Vault einlesen und indexieren")
    p_index.add_argument("pfad", nargs="?", help="Pfad zum Vault (Standard: VAULT_PATH aus .env)")
    p_index.add_argument("--max-zeichen", type=int, default=DEFAULT_MAX_CHARS)
    p_index.add_argument("--ueberlappung", type=int, default=DEFAULT_OVERLAP)

    p_ask = sub.add_parser("ask", help="Frage an den Vault stellen")
    p_ask.add_argument("frage", help="Die Frage in Anführungszeichen")
    p_ask.add_argument("-k", type=int, default=5, help="Anzahl Quellen-Chunks (Standard: 5)")
    p_ask.add_argument(
        "--nur-suche", action="store_true", help="Nur Quellen zeigen, kein Chat-Modell fragen"
    )

    p_eval = sub.add_parser("eval", help="Trefferquote mit dem Eval-Set messen")
    p_eval.add_argument(
        "--fragen",
        default="eval/questions.yaml",
        help="Pfad zum Eval-Set (Standard: eval/questions.yaml)",
    )
    p_eval.add_argument("--vault", default="demo_vault", help="Vault zum Eval-Set")
    p_eval.add_argument("-k", type=int, default=5, help="Treffer@k (Standard: 5)")
    p_eval.add_argument("--max-zeichen", type=int, default=DEFAULT_MAX_CHARS)
    p_eval.add_argument("--ueberlappung", type=int, default=DEFAULT_OVERLAP)
    p_eval.add_argument("--details", action="store_true", help="Ergebnis je Frage zeigen")
    p_eval.add_argument("--ausgabe", help="Ergebnis zusätzlich als Markdown-Datei speichern")
    return parser


def _cmd_index(args: argparse.Namespace, c: Components) -> int:
    vault = Path(args.pfad) if args.pfad else c.settings.vault_path
    start = time.perf_counter()
    r = index_vault(
        vault, c.embedder, c.store, max_chars=args.max_zeichen, overlap=args.ueberlappung
    )
    dauer = time.perf_counter() - start
    print(
        f"{r.notes} Notizen, {r.chunks} Chunks: {r.embedded} eingebettet, "
        f"{r.unchanged} unverändert, {r.deleted} gelöscht ({dauer:.1f} s, {c.embedder.model_name})"
    )
    return 0


def _quelle(nr: int, path: str, title: str, heading: str, vault_name: str) -> str:
    ort = title if not heading else f"{title} – {heading}"
    return f"  [{nr}] {ort}\n      {obsidian_url(vault_name, path)}"


def _cmd_ask(args: argparse.Namespace, c: Components) -> int:
    if c.store.count() == 0:
        print("Der Index ist leer. Erst `assistant index <pfad>` ausführen.", file=sys.stderr)
        return 1
    retriever = Retriever(c.embedder, c.store)
    vault_name = c.settings.vault_name
    if args.nur_suche:
        hits = retriever.search_notes(args.frage, args.k)
        print("Quellen:")
        for nr, h in enumerate(hits, start=1):
            print(_quelle(nr, h.chunk.path, h.chunk.title, h.chunk.heading, vault_name))
        return 0

    start = time.perf_counter()
    antwort = answer_question(args.frage, retriever, c.llm, args.k)
    dauer = time.perf_counter() - start
    print(antwort.text)
    if antwort.sources:
        print("\nQuellen:")
        for nr, h in enumerate(antwort.sources, start=1):
            print(_quelle(nr, h.chunk.path, h.chunk.title, h.chunk.heading, vault_name))
    print(f"\n({dauer:.1f} s, {c.llm.model_name})", file=sys.stderr)
    return 0


def _cmd_eval(args: argparse.Namespace, c: Components) -> int:
    # Eigener Index im Speicher: Der Eval stört so nie den echten Index.
    # Dank Embedding-Cache werden nur geänderte Chunks neu berechnet.
    store = InMemoryStore()
    index_vault(
        Path(args.vault), c.embedder, store, max_chars=args.max_zeichen, overlap=args.ueberlappung
    )
    fragen = load_questions(Path(args.fragen))
    ergebnis = evaluate(Retriever(c.embedder, store), fragen, args.k)

    kopf = (
        f"Eval: {len(fragen)} Fragen, Modell {c.embedder.model_name}, "
        f"Chunks max. {args.max_zeichen} Zeichen / Überlappung {args.ueberlappung}"
    )
    teile = [kopf, "", format_table(ergebnis)]
    if args.details:
        teile += ["", format_details(ergebnis)]
    text = "\n".join(teile)
    print(text)
    if args.ausgabe:
        ziel = Path(args.ausgabe)
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(text + "\n", encoding="utf-8")
        print(f"\nGespeichert: {ziel}", file=sys.stderr)
    return 0


_BEFEHLE = {"index": _cmd_index, "ask": _cmd_ask, "eval": _cmd_eval}


def main(
    argv: Sequence[str] | None = None,
    components_factory: ComponentsFactory = default_components,
) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    try:
        return _BEFEHLE[args.command](args, components_factory(settings))
    except OllamaError as e:
        print(
            f"Fehler: {e}\nLäuft Ollama unter {settings.ollama_url}? "
            "Ist der Gaming-PC wach und das Modell geladen (`ollama pull`)?",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
