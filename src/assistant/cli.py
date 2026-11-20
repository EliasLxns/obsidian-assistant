"""Kommandozeile: ``assistant index | ask | eval | serve | watch | nightly``.

Die Bausteine (Embedder, VectorStore, LLM) kommen aus einer ``ComponentsFactory``
(siehe ``assistant.components``). Im Normalbetrieb sind das Ollama und ChromaDB, in Tests Fakes.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from watchdog.observers.api import BaseObserver

from assistant.components import Components, ComponentsFactory, default_components
from assistant.config import Settings, load_settings
from assistant.evaluation import evaluate, format_details, format_table, load_questions
from assistant.index.embedder import FakeEmbedder, OllamaError
from assistant.index.store import InMemoryStore
from assistant.ingest.chunker import DEFAULT_MAX_CHARS, DEFAULT_OVERLAP
from assistant.ingest.indexer import IndexReport, index_notes, index_vault
from assistant.ingest.watcher import ChangeBatcher, watch_vault
from assistant.links import obsidian_url
from assistant.llm.answer import answer_question
from assistant.llm.client import ollama_busy, ollama_reachable, unload_models
from assistant.nightly import protocol
from assistant.nightly.guard import (
    im_fenster,
    parse_fenster,
    parse_uhrzeit,
    pause_aufheben,
    pause_setzen,
    sekunden_bis,
    warum_nicht,
)
from assistant.nightly.inbox import PROTOKOLL
from assistant.nightly.job import Optionen, run_nightly
from assistant.nightly.power import (
    PCFehler,
    Regeln,
    SshPC,
    ausschalten_wenn_ruhig,
    bewerten,
    messen,
)
from assistant.nightly.protocol import alle_laeufe
from assistant.nightly.vault_git import GitError, VaultGit
from assistant.nightly.wol import WakeOnLan
from assistant.retrieval.search import SUCHMODI, Retriever, suchmodus


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
    p_eval.add_argument(
        "--modus",
        choices=SUCHMODI,
        help="Suchmodus (Standard: SEARCH_MODE aus .env, sonst hybrid); bm25 läuft ohne Ollama",
    )
    p_eval.add_argument(
        "--links", action="store_true", help="Link-Erweiterung an (nur bm25 und hybrid)"
    )
    p_eval.add_argument("--details", action="store_true", help="Ergebnis je Frage zeigen")
    p_eval.add_argument("--ausgabe", help="Ergebnis zusätzlich als Markdown-Datei speichern")

    p_serve = sub.add_parser("serve", help="REST-API starten (/ask, /search, /status, /reindex)")
    p_serve.add_argument("--host", default="127.0.0.1", help="Im Container: 0.0.0.0")
    p_serve.add_argument("--port", type=int, default=8080)

    p_watch = sub.add_parser("watch", help="Vault beobachten und Änderungen nachindexieren")
    p_watch.add_argument("pfad", nargs="?", help="Pfad zum Vault (Standard: VAULT_PATH aus .env)")
    p_watch.add_argument(
        "--warten", type=float, default=2.0, help="Sekunden Ruhe vor dem Indexieren (Standard: 2)"
    )

    p_night = sub.add_parser(
        "nightly", help="Nachtjob: Inbox sortieren, Fragen beantworten (siehe `nightly -h`)"
    )
    p_night.add_argument(
        "--jetzt", action="store_true", help="Zeitfenster ignorieren und sofort laufen"
    )
    p_night.add_argument(
        "--probelauf", action="store_true", help="Alles berechnen, aber nichts schreiben"
    )
    p_night.add_argument("--vault", help="Pfad zum Vault (Standard: VAULT_PATH aus .env)")
    n_sub = p_night.add_subparsers(dest="aktion")
    n_sub.add_parser("dienst", help="Dauerbetrieb: jede Nacht um NIGHTLY_TIME laufen")
    n_pause = n_sub.add_parser("pause", help="Gaming-Schutz: Nachtjob pausieren")
    n_pause.add_argument("--stunden", type=float, help="Dauer (Standard: bis `weiter`)")
    n_pause.add_argument("--grund", default="", help="z. B. „LAN-Party“")
    n_sub.add_parser("weiter", help="Pause aufheben")
    n_sub.add_parser("laeufe", help="Letzte Läufe anzeigen")
    n_aus = n_sub.add_parser(
        "ausschalten", help="Gaming-PC per SSH ausschalten, sobald er lange genug ruhig ist"
    )
    n_aus.add_argument(
        "--pruefen", action="store_true", help="Nur messen und anzeigen, nicht ausschalten"
    )
    n_undo = n_sub.add_parser("rueckgaengig", help="Einen Lauf rückgängig machen")
    n_undo.add_argument("lauf", nargs="?", help="ID des Laufs (Standard: der letzte)")
    return parser


def _cmd_index(args: argparse.Namespace, c: Components) -> int:
    vault = Path(args.pfad) if args.pfad else c.settings.vault_path
    start = time.perf_counter()
    r = index_vault(
        vault, c.embedder, c.store, max_chars=args.max_zeichen, overlap=args.ueberlappung
    )
    dauer = time.perf_counter() - start
    print(f"{_bericht(r)} ({dauer:.1f} s, {c.embedder.model_name})")
    return 0


def _quelle(nr: int, path: str, title: str, heading: str, vault_name: str) -> str:
    ort = title if not heading else f"{title} – {heading}"
    return f"  [{nr}] {ort}\n      {obsidian_url(vault_name, path)}"


def _cmd_ask(args: argparse.Namespace, c: Components) -> int:
    if c.store.count() == 0:
        print("Der Index ist leer. Erst `assistant index <pfad>` ausführen.", file=sys.stderr)
        return 1
    s = c.settings
    retriever = Retriever(
        c.embedder,
        c.store,
        modus=s.suchmodus,
        erreichbar=lambda: ollama_reachable(s.ollama_url),
        link_erweiterung=s.link_erweiterung,
    )
    vault_name = s.vault_name
    if args.nur_suche:
        hits, modus = retriever.search_notes_mit_modus(args.frage, args.k)
        if modus != retriever.modus:
            print("Ollama nicht erreichbar: nur Stichwortsuche (BM25).", file=sys.stderr)
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
    modus = suchmodus(args.modus or c.settings.suchmodus)
    # BM25 braucht keine Vektoren: Platzhalter-Embeddings, damit der Eval ohne Ollama läuft.
    embedder = FakeEmbedder() if modus == "bm25" else c.embedder
    index_vault(
        Path(args.vault), embedder, store, max_chars=args.max_zeichen, overlap=args.ueberlappung
    )
    fragen = load_questions(Path(args.fragen))
    # Ohne Rückfall: Ist Ollama weg, scheitert der Eval, statt still nur BM25 zu messen.
    retriever = Retriever(
        embedder, store, modus=modus, rueckfall=False, link_erweiterung=args.links
    )
    ergebnis = evaluate(retriever, fragen, args.k)

    modell = "ohne Embeddings" if modus == "bm25" else f"Modell {embedder.model_name}"
    kopf = (
        f"Eval: {len(fragen)} Fragen, Suche {modus}{' + Links' if args.links else ''}, {modell}, "
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


def _cmd_serve(args: argparse.Namespace, c: Components) -> int:
    import uvicorn  # erst hier: index/ask/eval brauchen keinen Webserver

    from assistant.api import create_app

    uvicorn.run(create_app(c), host=args.host, port=args.port)
    return 0


def _bericht(r: IndexReport) -> str:
    return (
        f"{r.notes} Notizen, {r.chunks} Chunks: {r.embedded} eingebettet, "
        f"{r.unchanged} unverändert, {r.deleted} gelöscht"
    )


def start_watch(c: Components, vault: Path, delay: float) -> tuple[BaseObserver, ChangeBatcher]:
    """Indexiert einmal komplett und beobachtet danach den Vault."""
    print(f"Start: {_bericht(index_vault(vault, c.embedder, c.store))}", flush=True)

    def nachindexieren(pfade: set[Path]) -> None:
        r = index_notes(vault, pfade, c.embedder, c.store)
        print(f"Änderung: {_bericht(r)}", flush=True)

    batcher = ChangeBatcher(nachindexieren, delay=delay)
    return watch_vault(vault, batcher, polling=c.settings.watch_polling), batcher


def _cmd_watch(args: argparse.Namespace, c: Components) -> int:
    vault = Path(args.pfad) if args.pfad else c.settings.vault_path
    observer, batcher = start_watch(c, vault, args.warten)
    print(f"Beobachte {vault} … (Strg+C beendet)", flush=True)
    try:
        while observer.is_alive():
            observer.join(timeout=1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        batcher.stop()
        observer.join()
    return 0


def _nachtlauf(c: Components, vault: Path, args: argparse.Namespace) -> int:
    s = c.settings
    jetzt = datetime.now()
    if not args.jetzt:
        grund = warum_nicht(s.nightly_state_path, jetzt, parse_fenster(s.nightly_window))
        if grund:
            print(f"Nachtjob läuft nicht: {grund}", flush=True)
            return 0
    waker = WakeOnLan(s.gaming_pc_mac, s.wol_broadcast) if s.gaming_pc_mac else None
    lauf = run_nightly(
        c,
        vault,
        jetzt=jetzt,
        is_awake=lambda: ollama_reachable(s.ollama_url),
        waker=waker,
        optionen=Optionen(
            probelauf=args.probelauf, schon_wach_ueberspringen=s.nightly_skip_if_awake
        ),
        wol_timeout_s=s.wol_wait_s,
        entladen=lambda: _entladen(s.ollama_url, [s.chat_model, s.embed_model]),
        ausschalten=_ausschalter(s),
    )
    print(f"Lauf {lauf.id}{' (Probelauf)' if lauf.probelauf else ''}: PC {lauf.pc}", flush=True)
    for h in lauf.hinweise:
        print(f"  {h}")
    for a in lauf.aktionen:
        wohin = f" → {a.ziel}" if a.ziel and a.ziel != a.quelle else ""
        print(f"  [{a.art}] {a.quelle}{wohin} ({a.details})")
    return 1 if any(h.startswith("Abgebrochen") for h in lauf.hinweise) else 0


def _gaming_pc(s: Settings) -> SshPC | None:
    if not s.gaming_pc_ssh:
        return None
    return SshPC(s.gaming_pc_ssh, s.gaming_pc_ssh_key, s.nightly_state_path / "known_hosts")


def _regeln(s: Settings) -> Regeln:
    return Regeln(ruhe_min=s.shutdown_ruhe_min, max_warten_min=s.shutdown_max_warten_min)


def _ausschalter(s: Settings) -> Callable[[], str] | None:
    """Ohne ``GAMING_PC_SSH`` wird nie ausgeschaltet."""
    pc = _gaming_pc(s)
    if pc is None:
        return None
    return lambda: ausschalten_wenn_ruhig(pc, lambda: ollama_busy(s.ollama_url), _regeln(s))


def _cmd_ausschalten(s: Settings, pruefen: bool) -> int:
    pc = _gaming_pc(s)
    if pc is None:
        print("GAMING_PC_SSH ist nicht gesetzt, Ausschalten ist aus.", file=sys.stderr)
        return 1
    if pruefen:
        try:
            m = messen(pc, lambda: ollama_busy(s.ollama_url))
        except PCFehler as e:
            print(f"Fehler: {e}", file=sys.stderr)
            return 2
        gpu = "unbekannt" if m.gpu is None else f"{m.gpu:.0f} %"
        print(f"Ollama beschäftigt: {'ja' if m.ollama_aktiv else 'nein'}")
        print(f"PC gesperrt: {'ja' if m.gesperrt else 'nein'}")
        print(f"GPU: {gpu}")
        print(f"Bewertung: {bewerten(m, _regeln(s))[1]}")
        return 0
    print(ausschalten_wenn_ruhig(pc, lambda: ollama_busy(s.ollama_url), _regeln(s)), flush=True)
    return 0


def _entladen(url: str, modelle: list[str]) -> None:
    for m in unload_models(url, modelle):
        print(f"Hinweis: Modell {m} ließ sich nicht entladen.", file=sys.stderr)


def _nacht_dienst(c: Components, vault: Path, args: argparse.Namespace) -> int:
    s = c.settings
    # Im Dienst gelten Zeitfenster und Pause immer, auch wenn beim Start --jetzt stand.
    args = argparse.Namespace(**{**vars(args), "jetzt": False})
    start = parse_uhrzeit(s.nightly_time)
    startzeit = datetime.now().replace(hour=start.hour, minute=start.minute)
    if not im_fenster(startzeit, parse_fenster(s.nightly_window)):
        print(f"Warnung: NIGHTLY_TIME {s.nightly_time} liegt außerhalb von NIGHTLY_WINDOW.")
    while True:
        warten = sekunden_bis(datetime.now(), start)
        print(f"Nächster Nachtlauf um {s.nightly_time} (in {warten / 3600:.1f} h)", flush=True)
        time.sleep(warten)
        try:
            _nachtlauf(c, vault, args)
        except Exception as e:  # Der Dienst soll weiterlaufen, der Fehler steht im Log.
            print(f"Fehler im Nachtlauf: {e}", file=sys.stderr, flush=True)
        time.sleep(61)  # nicht zweimal in derselben Minute starten


def _cmd_nightly(args: argparse.Namespace, c: Components) -> int:
    s = c.settings
    vault = Path(args.vault) if args.vault else s.vault_path
    state = s.nightly_state_path
    match args.aktion:
        case "dienst":
            return _nacht_dienst(c, vault, args)
        case "pause":
            bis = datetime.now() + timedelta(hours=args.stunden) if args.stunden else None
            pause_setzen(state, bis, args.grund)
            print(f"Nachtjob pausiert{f' bis {bis:%d.%m. %H:%M}' if bis else ' bis `weiter`'}.")
            return 0
        case "weiter":
            print("Pause aufgehoben." if pause_aufheben(state) else "Es war keine Pause aktiv.")
            return 0
        case "laeufe":
            for datei in alle_laeufe(state)[-10:]:
                lauf = protocol.laden(datei)
                arten = Counter(a.art for a in lauf.aktionen)
                zahlen = ", ".join(f"{n} {art}" for art, n in arten.items()) or "nichts zu tun"
                probe = " (Probelauf)" if lauf.probelauf else ""
                print(f"{lauf.id}{probe}: PC {lauf.pc}; {zahlen}")
            return 0
        case "rueckgaengig":
            return _rueckgaengig(vault, state, args.lauf, s.inbox_dir)
        case "ausschalten":
            return _cmd_ausschalten(s, args.pruefen)
        case _:
            return _nachtlauf(c, vault, args)


def _rueckgaengig(vault: Path, state: Path, lauf_id: str | None, inbox_dir: str) -> int:
    lauf: protocol.Lauf | None = None
    if lauf_id:
        datei = next((d for d in alle_laeufe(state) if d.stem == lauf_id), None)
        lauf = protocol.laden(datei) if datei else None
    else:
        # Neuester echter Lauf, der etwas geändert hat (leere oder abgebrochene zählen nicht)
        for datei in reversed(alle_laeufe(state)):
            kandidat = protocol.laden(datei)
            erledigt = kandidat.probelauf or kandidat.rueckgaengig
            if not erledigt and any(a.art != "fehler" for a in kandidat.aktionen):
                lauf = kandidat
                break
    if lauf is None:
        print("Keinen passenden Lauf gefunden (`assistant nightly laeufe`).", file=sys.stderr)
        return 1
    if lauf.probelauf:
        print(f"Lauf {lauf.id} war ein Probelauf, es gibt nichts zurückzunehmen.")
        return 0
    if lauf.rueckgaengig:
        print(f"Lauf {lauf.id} wurde schon am {lauf.rueckgaengig} rückgängig gemacht.")
        return 0
    md = vault / inbox_dir / PROTOKOLL / f"Nachtjob {lauf.id}.md"
    for zeile in protocol.rueckgaengig(vault, lauf, protokoll=md):
        print(zeile)
    lauf.rueckgaengig = datetime.now().isoformat(timespec="seconds")
    protocol.speichern(state, lauf)
    git = VaultGit(vault)
    if git.ist_repo():
        # Nur, was der Lauf angefasst hat: eigene Änderungen im Vault bleiben uncommittet.
        pfade = {p for a in lauf.aktionen for p in (a.quelle, a.ziel) if p}
        pfade.add(md.relative_to(vault).as_posix())
        try:
            if git.commit(f"Nachtjob: Lauf {lauf.id} rückgängig", sorted(pfade)):
                print("Git-Commit erstellt.")
        except GitError as e:
            print(f"Git-Commit fehlgeschlagen: {e}", file=sys.stderr)
    return 0


_BEFEHLE = {
    "index": _cmd_index,
    "ask": _cmd_ask,
    "eval": _cmd_eval,
    "serve": _cmd_serve,
    "watch": _cmd_watch,
    "nightly": _cmd_nightly,
}


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
