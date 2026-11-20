# CLAUDE.md – Obsidian-Assistent

Planungsquelle ist das Projekthandbuch (Claude Doc). Dieses Dokument fasst Ziel, Struktur, Befehle und Regeln für die Arbeit im Repo zusammen. Antworte auf Deutsch.

## Ziel

Der Obsidian-Assistent macht einen Obsidian-Vault durchsuchbar und befragbar, komplett lokal, und sortiert nachts die Inbox. Er läuft auf einem Mini-PC (HP ProDesk 400 G5, Docker Compose), die KI über Ollama auf einem Gaming-PC mit RTX 2070 (8 GB VRAM), der per Wake-on-LAN geweckt wird. Gleichzeitig ist er ein Portfolio-Projekt für Bewerbungen: Code, Tests und Doku sollen erklärbar und sauber sein.

**Version 1 kann:**
- Fragen an den Vault beantworten, immer mit Quellen-Links, die die Notiz in Obsidian öffnen
- Neue Notizen in `00 Inbox` nachts verschlagworten, verlinken und einsortieren, mit Protokoll und Rückgängig-Möglichkeit
- „Frage:“-Notizen aus der Inbox über Nacht beantworten
- Ein Dashboard mit Suche, Inbox-Status, Vault-Statistik und Systemstatus

**Bewusst nicht in Version 1:**
- Keine Cloud-KI, keine Daten außer Haus
- Kein Bearbeiten bestehender Notizen durch die KI, nur Einsortieren neuer
- Kein öffentlicher Zugang aus dem Internet
- Kein Zugriff vom Firmen-PC außer über normales Obsidian Sync

**Erfolgskriterien:** Treffer@5 ≥ 80 % auf dem Eval-Set, Antwort < 15 s bei wachem Gaming-PC, Nachtjob 14 Nächte ohne Eingreifen, öffentliches Repo mit README, Architekturbild, Demo-Video und Eval-Ergebnissen.

## Komponenten und Schnittstellen

| Komponente | Aufgabe | Technik | Ort | Schnittstelle |
|---|---|---|---|---|
| Sync | Hält den Vault aktuell | `obsidian-headless` | Mini-PC (systemd) | Dateisystem `~/Obsidian/<Vault>` |
| Indexer | Erkennt Änderungen, parst, chunkt, bettet ein | Python, `watchdog` | Mini-PC (Container) | Liest Vault nur lesend, schreibt in Chroma |
| Vektor-DB | Speichert Chunks, Vektoren, Metadaten | ChromaDB | Mini-PC (Container) | HTTP, intern Port 8000 |
| Retriever | Hybrid-Suche + Link-Erweiterung | Python, BM25 + Chroma | Teil der API | Python-Interface |
| API | Fragen, Suche, Status, Reindex | FastAPI | Mini-PC (Container) | REST: `/ask`, `/search`, `/status`, `/reindex` |
| Nachtjob | Inbox sortieren, Fragen beantworten, PC wecken | Python + Scheduler, `wakeonlan` | Mini-PC (Container, `network_mode: host`) | Schreibt nur in `00 Inbox`-Dateien, Git-Commit davor |
| LLM + Embeddings | Antworten und Vektoren erzeugen | Ollama, `bge-m3` + 7–8B-Modell | Gaming-PC | HTTP Port 11434 |
| Dashboard | Suche, Inbox, Statistik, Systemstatus | Streamlit, später React oder Blazor | Mini-PC (Container) | Ruft die API |
| Obsidian-Plugin | Suche in der Seitenleiste | TypeScript, `requestUrl` | Jedes Obsidian | Ruft die API (Heimnetz/Tailscale) |

## Technische Entscheidungen

Jede Entscheidung ist hinter einem Interface gekapselt, damit sie tauschbar bleibt. Änderungen werden im Handbuch mit Datum und Grund nachgetragen.

- Python 3.12, **ohne LangChain/LlamaIndex**: jeden Schritt selbst verstehen und erklären können
- Embeddings: `bge-m3` (mehrsprachig); Alternative `nomic-embed-text`
- Chat-Modell: 7–8B, Q4, per Eval gewählt (passt in 8 GB VRAM)
- Vektor-DB: ChromaDB
- Suche: Hybrid aus Vektor + BM25 (findet auch exakte Begriffe)
- Chunking: nach Überschriften, Längenlimit mit Überlappung
- API: FastAPI · Dashboard: Streamlit, dann React oder Blazor
- Vault-Zugang Server: Obsidian Headless Sync · Fernzugriff: Tailscale
- Nachtjob: nur `00 Inbox`, Git-Commit vor jedem Lauf

## Struktur

```
src/assistant/
  ingest/      # Parser, Chunker, Watcher
  index/       # Embedder + VectorStore (Interfaces + Ollama/Chroma)
  retrieval/   # Hybrid-Suche, Link-Erweiterung
  llm/         # Prompts, Ollama-Client
  nightly/     # Inbox-Sortierer, Fragen-Beantworter, Wake-on-LAN
  api/         # FastAPI
  cli.py       # assistant index | ask | eval
dashboard/        # Streamlit (nur über die API, Theme in .streamlit/config.toml), später Frontend
obsidian-plugin/  # TypeScript-Plugin
eval/questions.yaml
demo_vault/       # fiktive Notizen, drei Themen: Homelab/Docker, Garten, Laufen
tests/
docs/architecture.md
docker-compose.yml
```

## Befehle

```bash
pip install -e ".[dev]"          # Installation inkl. Dev-Tools
ruff check . && ruff format .    # Lint + Formatierung
pyright                          # Typprüfung (strict)
pytest                           # Tests, laufen ohne Ollama

assistant index demo_vault/      # ab Phase 1
assistant ask "Welchen Port nutzt Ollama?"
assistant eval                   # Treffer@1 / Treffer@5 als Tabelle
assistant serve                  # API auf :8080 (ab Phase 2)
cd dashboard && streamlit run app.py   # Dashboard auf :8501 (ab Phase 4, braucht die API)
cd obsidian-plugin && npm ci && npm test && npm run build   # Plugin (ab Phase 5)
```

## Claude-Code-Hooks

`.claude/settings.json` startet drei Hooks aus `.claude/hooks/` (Tests in `tests/test_claude_hooks.py`):

- **`check_python.py`** (nach jedem Edit/Write einer `.py`-Datei): `ruff check --fix`, `ruff format`, dann `ruff check` und `pyright`. Restfehler gehen sofort an Claude zurück
- **`run_tests.py`** (wenn Claude fertig sein will): `pytest -x -q`, sobald Python-Dateien geändert sind. Rote Tests blockieren einmal, danach nur noch eine Warnung
- **`capture_rules.py`** (bei jeder Nachricht): erkennt Sätze wie „ab jetzt“, „immer“, „nie“, „merk dir“ und lässt Claude die Regel unten unter „Regeln“ eintragen

Fehlt `ruff`, `pyright` oder `pytest`, überspringen die Hooks still. Deshalb zuerst `pip install -e ".[dev]"`.

## Regeln

- Konfiguration nur über `.env` (Ollama-URL, Vault-Pfad, Modellnamen); `.env` steht in `.gitignore`, Vorlage ist `.env.example`
- Formatierung und Linting mit `ruff`, Typprüfung mit `pyright`, Tests mit `pytest`; die GitHub Action prüft alles bei jedem Push
- Ein Branch pro Funktion, kleine Commits im Stil `feat:`, `fix:`, `docs:`, `test:`, `chore:`
- Tests laufen ohne Ollama über einen `FakeEmbedder` und ein `FakeLLM`
- **Niemals echte Notizen ins Repo, in Logs oder Issues.** Nur `demo_vault/` verwenden
- **Nichts Persönliches ins öffentliche Repo:** keine echten IPs, MAC-Adressen, Pfade (z. B. Laufwerke, Benutzerordner), Vault-, Benutzer- oder Rechnernamen. Nur Platzhalter oder die fiktiven Demo-Werte; echte Werte gehören in `.env` oder ins private Handbuch
- Die KI bearbeitet keine bestehenden Notizen; der Nachtjob schreibt nur in `00 Inbox`, mit Git-Commit davor, unsichere Fälle nach `00 Inbox/Prüfen`
- Keine Frameworks wie LangChain/LlamaIndex einführen
- Jede Änderung an Chunking, Modell oder Suche mit `assistant eval` messen und das Ergebnis festhalten
- Vor jedem Merge: `code-review` in Claude Code laufen lassen

## Eval-Set

`eval/questions.yaml`, Pfade relativ zu `demo_vault/`:

```yaml
- frage: "Wie starte ich meine Container?"
  erwartet: "03 Wissen/Docker/Compose.md"
  typ: umschreibung        # exakt | umschreibung | mehrere
```

Bei `typ: mehrere` ist `erwartet` eine Liste. Wird der Demo-Vault geändert, prüft `tests/test_demo_vault.py`, dass alle erwarteten Notizen und Wikilinks noch existieren.
