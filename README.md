# Obsidian-Assistent

Ein lokaler RAG-Assistent für einen Obsidian-Vault. Er beantwortet Fragen an die eigenen Notizen mit Quellen-Links, sortiert nachts neue Notizen aus der Inbox ein und beantwortet „Frage:“-Notizen. Alles läuft zu Hause: keine Cloud-KI, keine Daten außer Haus.

> **Status:** Phase 0 (Vorbereitung). Das Repo enthält Struktur, Demo-Vault und Eval-Set; der Code folgt ab Phase 1.

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

Ab Phase 1:

```bash
assistant index demo_vault/
assistant ask "Welchen Port nutzt Ollama?"
assistant eval
```

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
