# Obsidian-Assistent

Ein lokaler RAG-Assistent für einen Obsidian-Vault. Er beantwortet Fragen an die eigenen Notizen mit Quellen-Links, sortiert nachts neue Notizen aus der Inbox ein und beantwortet „Frage:“-Notizen. Alles läuft zu Hause: keine Cloud-KI, keine Daten außer Haus.

> **Status:** Phase 2 (API und Docker). CLI `index`, `ask`, `eval` aus Phase 1, dazu REST-API (`/ask`, `/search`, `/status`, `/reindex`), ein Watcher, der nur geänderte Notizen nachindexiert, und Docker Compose mit API, Indexer und ChromaDB. Erster Eval-Lauf mit Ollama: bge-m3 erreicht Treffer@1 95 % und Treffer@5 100 % ([Ergebnisse](docs/eval-ergebnisse.md)).

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
assistant serve                              # REST-API auf http://127.0.0.1:8080, Doku unter /docs
assistant watch                              # Vault beobachten, Änderungen nachindexieren
```

## Betrieb mit Docker Compose

```bash
cp .env.example .env        # VAULT_HOST_PATH auf den Vault, Rest passt für den Start
docker compose up -d --build
curl localhost:8080/status
```

**Vorerst auf dem Gaming-PC:** Solange der Mini-PC fehlt, läuft der Stack mit Docker Desktop auf dem Gaming-PC selbst. Ollama läuft dort direkt (nicht im Container) und ist aus den Containern über `host.docker.internal:11434` erreichbar, das ist der Standard. Weil Docker Desktop unter Windows keine Dateiänderungen in Container meldet, fragt der Watcher den Vault alle 10 s ab (`WATCH_POLLING=true`). Zum Spielen lässt sich alles mit `docker compose stop` anhalten.

**Später auf dem Mini-PC:** Repo und `.env` mitnehmen, in `.env` `OLLAMA_URL_DOCKER=http://<IP-des-Gaming-PCs>:11434` und `WATCH_POLLING=false` setzen, `VAULT_HOST_PATH` auf den Headless-Sync-Ordner. Der Index wird beim ersten Start neu aufgebaut.

| Dienst | Aufgabe |
|---|---|
| `chroma` | ChromaDB, nur im internen Compose-Netz erreichbar, Daten im Volume `chroma` |
| `indexer` | `assistant watch`: beim Start alles indexieren, danach nur geänderte Notizen |
| `api` | `assistant serve` auf Port 8080 |

Der Vault wird nur lesend eingebunden, die Container laufen ohne Root-Rechte. Ollama läuft nicht im Compose, sondern direkt auf dem Gaming-PC.

### API

| Endpunkt | Zweck |
|---|---|
| `POST /ask` `{"frage": "...", "k": 5}` | Antwort mit nummerierten Quellen (`obsidian://`-Link, Auszug, Score) |
| `POST /search` `{"frage": "...", "k": 5}` | Nur Quellen, ohne Chat-Modell |
| `GET /status` | Anzahl Chunks, Modelle, letzter Indexlauf, ist Ollama erreichbar |
| `POST /reindex` | Vault abgleichen, nur Geändertes wird eingebettet |

Schläft der Gaming-PC, antworten `/ask`, `/search` und `/reindex` mit `503` und einem Hinweis; ein leerer Index ergibt `409`.

## Aufbau des Codes

| Modul | Aufgabe |
|---|---|
| `ingest/parser.py` | Frontmatter, Tags, Wikilinks und Überschriften aus Markdown |
| `ingest/chunker.py` | Ein Chunk pro Abschnitt, lange Abschnitte mit Längenlimit und Überlappung |
| `ingest/indexer.py` | Vault oder einzelne Notizen indexieren, nur geänderte Chunks einbetten, gelöschte entfernen |
| `ingest/watcher.py` | `watchdog`-Meldungen sammeln und nach einer Ruhepause gebündelt nachindexieren, bei Fehlern erneut versuchen |
| `index/embedder.py` | Interface `Embedder`, `OllamaEmbedder` (Batching, SQLite-Hash-Cache), `FakeEmbedder` |
| `index/store.py` | Interface `VectorStore`, `ChromaStore` (Metadaten: Pfad, Überschrift, Tags, Hash, Modell), `InMemoryStore` |
| `retrieval/search.py` | Vektorsuche, beste Notizen; Hybrid-Suche folgt hinter derselben Schnittstelle |
| `llm/` | Interface `LLM`, `OllamaLLM`, `FakeLLM`, Prompts, Antwort mit nummerierten Quellen |
| `evaluation.py` | Eval-Set laden, Treffer@k je Fragetyp |
| `api/app.py` | FastAPI: `/ask`, `/search`, `/status`, `/reindex` |
| `components.py` | Baut Embedder, VectorStore und LLM aus der Konfiguration (Chroma lokal oder per HTTP) |
| `cli.py` | Befehle `index`, `ask`, `eval`, `serve` und `watch` |

Alle Tests laufen ohne Ollama: mit `FakeEmbedder` (Bag-of-Words über Hashing), `FakeLLM` und einem simulierten Ollama-Server (`httpx.MockTransport`). Die API wird mit dem `TestClient` von FastAPI getestet, der Watcher mit einem echten `watchdog`-Observer auf einer Kopie des Demo-Vaults.

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
