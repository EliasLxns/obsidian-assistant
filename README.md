# Obsidian-Assistent

Ein lokaler RAG-Assistent für einen Obsidian-Vault. Er beantwortet Fragen an die eigenen Notizen mit Quellen-Links, sortiert nachts neue Notizen aus der Inbox ein und beantwortet „Frage:“-Notizen. Alles läuft zu Hause: keine Cloud-KI, keine Daten außer Haus.

> **Status:** Phase 1 (CLI-MVP). `assistant index`, `ask` und `eval` sind implementiert und getestet; erster Eval-Lauf mit Ollama: bge-m3 erreicht Treffer@1 95 % und Treffer@5 100 % ([Ergebnisse](docs/eval-ergebnisse.md)).

## Funktionen (Version 1)

- Fragen an den Vault beantworten, immer mit Quellen-Links (`obsidian://`), die die Notiz direkt öffnen
- Neue Notizen in `00 Inbox` nachts verschlagworten, verlinken und einsortieren, mit Protokoll und Rückgängig-Möglichkeit
- „Frage:“-Notizen aus der Inbox über Nacht beantworten
- Dashboard mit Suche, Inbox-Status, Vault-Statistik und Systemstatus

## Architektur

```
Obsidian Sync ──► Mini-PC (Docker Compose)                      Gaming-PC (RTX 2070)
                  ├─ Headless Sync  → Vault (nur lesend)
                  ├─ Indexer        → ChromaDB ◄──── Embeddings ── Ollama (bge-m3)
                  ├─ API (FastAPI)  ── Hybrid-Suche (BM25 + Vektor) ── Ollama (7–8B, Q4)
                  ├─ Nachtjob       ── Wake-on-LAN ─────────────────► weckt den PC
                  └─ Dashboard
Obsidian-Plugin ──► API (Heimnetz / Tailscale)
```

Details: [docs/architecture.md](docs/architecture.md)

## Tech-Stack

Python 3.12 · ohne LangChain/LlamaIndex · Ollama (`bge-m3` + 7–8B-Modell) · ChromaDB · BM25 · FastAPI · Streamlit (später React oder Blazor) · TypeScript-Plugin · Docker Compose · Tailscale

## Schnellstart (Entwicklung)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # Ollama-URL und Vault-Pfad anpassen

ruff check . && ruff format --check . && pyright && pytest
```

Mit Ollama (Embedding- und Chat-Modell vorher holen: `ollama pull bge-m3`, `ollama pull qwen2.5:7b-instruct-q4_K_M`):

```bash
assistant index demo_vault/                  # nur Geändertes wird neu eingebettet
assistant ask "Welchen Port nutzt Ollama?"   # Antwort mit Quellen als obsidian://-Links
assistant ask --nur-suche "Eisheiligen"      # nur Quellen, ohne Chat-Modell
assistant eval --details                     # Treffer@1 / Treffer@5 als Tabelle
```

## Aufbau des Codes

| Modul | Aufgabe |
|---|---|
| `ingest/parser.py` | Frontmatter, Tags, Wikilinks und Überschriften aus Markdown |
| `ingest/chunker.py` | Ein Chunk pro Abschnitt, lange Abschnitte mit Längenlimit und Überlappung |
| `ingest/indexer.py` | Vault indexieren, nur geänderte Chunks einbetten, gelöschte entfernen |
| `index/embedder.py` | Interface `Embedder`, `OllamaEmbedder` (Batching, SQLite-Hash-Cache), `FakeEmbedder` |
| `index/store.py` | Interface `VectorStore`, `ChromaStore` (Metadaten: Pfad, Überschrift, Tags, Hash, Modell), `InMemoryStore` |
| `retrieval/search.py` | Vektorsuche, beste Notizen; Hybrid-Suche folgt hinter derselben Schnittstelle |
| `llm/` | Interface `LLM`, `OllamaLLM`, `FakeLLM`, Prompts, Antwort mit nummerierten Quellen |
| `evaluation.py` | Eval-Set laden, Treffer@k je Fragetyp |
| `cli.py` | Befehle `index`, `ask` und `eval` |

Alle Tests laufen ohne Ollama: mit `FakeEmbedder` (Bag-of-Words über Hashing), `FakeLLM` und einem simulierten Ollama-Server (`httpx.MockTransport`).

## Demo-Vault und Evaluation

`demo_vault/` enthält 25 fiktive Notizen zu drei klar getrennten Themen (Homelab/Docker, Garten, Laufen). Echte Notizen kommen nie ins Repo.

`eval/questions.yaml` enthält 20 Fragen mit der Notiz, die gefunden werden soll: exakte Begriffe, Umschreibungen und Fragen, die mehrere Notizen brauchen. Ziel für Version 1: Treffer@5 ≥ 80 %, Treffer@1 ≥ 50 %, Antwortzeit < 15 s.

## Roadmap

| Phase | Inhalt |
|---|---|
| 0 | Vorbereitung: Repo, Demo-Vault, Eval-Set, Hardware |
| 1 | CLI-MVP: `index`, `ask`, `eval` |
| 2 | FastAPI, Docker Compose, Mini-PC, Headless Sync, inkrementelles Indexieren |
| 3 | Nachtjob: Inbox-Sortierer, Fragen-Beantworter, Wake-on-LAN |
| 4 | Dashboard: Streamlit, dann React oder Blazor |
| 5 | Obsidian-Plugin, Hybrid-Suche + Link-Erweiterung, Demo-Video, Eval-Ergebnisse |
