# Architektur

Drei Ebenen: Vault und Sync, Dienste auf dem Mini-PC, KI auf dem Gaming-PC.

```mermaid
flowchart LR
    subgraph Clients
        OBS[Obsidian-Apps] 
        PLUG[Obsidian-Plugin]
        DASH[Dashboard]
    end
    subgraph MiniPC["Mini-PC · Docker Compose"]
        SYNC[Headless Sync] --> VAULT[(Vault, nur lesend)]
        VAULT --> IDX[Indexer]
        IDX --> CHROMA[(ChromaDB)]
        API[FastAPI<br/>/ask /search /status /reindex<br/>/inbox /vault /nachtjob/pause]
        RET[Retriever<br/>BM25 + Vektor + Links]
        API --> RET --> CHROMA
        NIGHT[Nachtjob] -->|schreibt nur 00 Inbox| VAULT
    end
    subgraph Gaming["Gaming-PC · RTX 2070"]
        OLL[Ollama :11434<br/>bge-m3 + 7–8B]
    end
    OBS -. Obsidian Sync .-> SYNC
    PLUG --> API
    DASH --> API
    IDX -->|Embeddings| OLL
    API -->|Antworten| OLL
    NIGHT -->|Wake-on-LAN| Gaming
```

## Datenfluss einer Frage

1. Plugin oder Dashboard schickt die Frage an `/ask`.
2. Der Retriever kombiniert BM25 und Vektorsuche (Reciprocal Rank Fusion) und ergänzt Notizen, auf die die besten Treffer verlinken.
3. Die besten Chunks gehen mit einem Prompt an das Chat-Modell in Ollama.
4. Die Antwort kommt mit Quellen als `obsidian://`-Links zurück.

## Schnittstellen im Code

`Embedder`, `VectorStore` und `LLM` sind Interfaces. Für Tests gibt es `FakeEmbedder` und `FakeLLM`, damit die Tests ohne Ollama laufen. Diese Teile entstehen in Phase 1.

## Phase 2: Dienste und inkrementelles Indexieren

Bis der Mini-PC da ist, laufen die Container mit Docker Desktop auf dem Gaming-PC und erreichen Ollama über `host.docker.internal`. Für den Umzug ändern sich nur zwei Werte in `.env` (`OLLAMA_URL_DOCKER`, `WATCH_POLLING`).

Ein Docker-Image, zwei Befehle: `assistant watch` (Indexer) und `assistant serve` (API). Beide sprechen ChromaDB per HTTP an (`CHROMA_HOST=chroma`) und teilen sich den Embedding-Cache im Volume `cache`.

```mermaid
sequenceDiagram
    participant FS as Vault (nur lesend)
    participant W as watchdog
    participant B as ChangeBatcher
    participant I as index_notes
    participant O as Ollama
    participant C as ChromaDB
    FS->>W: Datei geändert / neu / gelöscht / verschoben
    W->>B: Pfad (nur .md, keine versteckten Ordner)
    Note over B: wartet 2 s Ruhe,<br/>sammelt alle Pfade
    B->>I: geänderte Pfade
    I->>C: Fingerabdrücke dieser Notizen
    I->>O: nur Chunks mit neuem Hash
    I->>C: upsert + veraltete Chunks löschen
```

**Hash-Vergleich:** Jeder Chunk hat einen Fingerabdruck aus SHA-256 seines Textes und dem Embedding-Modell. Beim Nachindexieren werden nur die Chunks der gemeldeten Notizen mit dem Index verglichen. Gleicher Fingerabdruck heißt: kein Aufruf an Ollama. Wechselt das Modell, ändern sich alle Fingerabdrücke und alles wird neu eingebettet.

**Warum sammeln?** Obsidian speichert beim Tippen alle paar Sekunden, Sync schreibt viele Dateien kurz hintereinander. Der `ChangeBatcher` wartet, bis zwei Sekunden lang nichts passiert, und indexiert dann einmal. Schläft der Gaming-PC, bleiben die Pfade vorgemerkt und werden nach 60 Sekunden erneut versucht.

**Fehlerbilder der API:** Ollama nicht erreichbar → `503` mit Hinweis auf den Gaming-PC. Leerer Index → `409`. Zwei `/reindex` gleichzeitig → der zweite bekommt `409`.

## Phase 3: Nachtjob

Der Nachtjob ist ein eigener Container (`assistant nightly dienst`, Compose-Profil `nachtjob`). Er schläft bis `NIGHTLY_TIME` und arbeitet dann die Inbox ab.

```mermaid
sequenceDiagram
    participant N as Nachtjob
    participant G as Gaming-PC / Ollama
    participant V as Vault (Git)
    participant C as ChromaDB
    N->>N: Gaming-Schutz: Zeitfenster? Pause?
    N->>G: /api/tags erreichbar?
    alt schläft
        N->>G: Magic Packet (alle 60 s, max. WOL_WAIT_S)
    end
    N->>V: git commit „Stand vor Lauf“
    N->>C: Index abgleichen
    loop jede Notiz direkt in 00 Inbox
        alt „Frage:“-Notiz
            N->>C: Suche (ohne Inbox)
            N->>G: Antwort mit Quellen
            N->>V: Antwort an die Frage-Notiz anhängen
        else neue Notiz
            N->>C: verwandte Notizen
            N->>G: JSON: Ordner, Tags, sicher?
            N->>V: Tags + Links, verschieben (oder 00 Inbox/Prüfen)
        end
    end
    N->>V: Protokoll-Notiz, git commit „Lauf …“
    N->>G: Modelle entladen (keep_alive 0)
    opt PC wurde vom Nachtjob geweckt
        loop jede Minute, bis 15 min Ruhe
            N->>G: SSH: gesperrt? (LogonUI), nvidia-smi; HTTP: /api/ps
        end
        N->>G: SSH: shutdown /s /t 60
    end
```

**Warum JSON und eine feste Ordnerliste?** Ein 7–8B-Modell erfindet sonst gern Ordner. Das Modell bekommt die vorhandenen Ordner mit einigen Notiztiteln als Beispiel und muss einen davon wählen; Ollama erzwingt mit `format: "json"` gültiges JSON. Alles, was nicht passt (unbekannter Ordner, „sicher“ nicht `true`, kaputtes JSON), landet in `00 Inbox/Prüfen`.

**Rückgängig ohne Git-Kenntnisse:** Der Lauf speichert pro Notiz Quelle, Ziel, Originaltext und den Hash des geschriebenen Textes (`NIGHTLY_STATE_PATH/laeufe/<id>.json`). Rückgängig schreibt den Originaltext zurück, aber nur, wenn die Notiz noch genau so aussieht, wie der Nachtjob sie hinterlassen hat. Zurück kommt sie Byte für Byte, auch mit ihren Zeilenenden (CRLF aus Windows bleibt CRLF). Danach verschwindet die Protokoll-Notiz, oder sie bekommt einen Vermerk, wenn etwas übersprungen wurde, und ein Git-Commit „… rückgängig“ hält den Stand fest. Git bleibt zusätzlich als Sicherheitsnetz.

**Welche Notizen werden verlinkt?** Nur ähnliche Notizen mit Kosinus ≥ 0,5, die höchstens 0,1 hinter dem besten Treffer liegen. Im Probelauf mit `bge-m3` erreichten selbst fremde Notizen 0,44, passende 0,53 bis 0,71. Die Werte werden mit echten Inbox-Notizen nachjustiert. Damit die Tags einheitlich bleiben, bekommt das Modell die vorhandenen Tags des Vaults und soll sie wiederverwenden, mit Umlauten.

**Antworten nur aus den Quellen:** Der Antwort-Prompt verlangt „du“, keine dazuerfundenen Gründe und eine Quellennummer je Satz. Im Code bleiben danach nur die Quellen stehen, die die Antwort wirklich zitiert, neu durchnummeriert.

**Gaming-Schutz:** Vom Server aus ist nicht sichtbar, ob ein Spiel läuft. Deshalb einfache, nachvollziehbare Regeln: nur im Zeitfenster, Pause-Schalter, Modelle sofort entladen, optional einen schon wachen PC in Ruhe lassen.

**Netz:** Ein UDP-Broadcast verlässt das Docker-Bridge-Netz nicht. Auf dem Mini-PC läuft der Nachtjob deshalb mit `network_mode: host` (`compose.minipc.yml`) und erreicht ChromaDB über `127.0.0.1:8000`.

**Ausschalten:** Wake-on-LAN kann nur einschalten. Zum Ausschalten nutzt der Nachtjob den eingebauten OpenSSH-Server von Windows. Ruhe heißt: kein Modell in Ollama geladen (sonst läuft gerade Arbeit), PC gesperrt (niemand davor), GPU ruhig. Details: [gaming-pc-ausschalten.md](gaming-pc-ausschalten.md).

## Phase 4: Dashboard

Das Dashboard ist ein eigener Container und kennt nur die API. Alles, was es zeigt, kommt über REST:

```mermaid
flowchart LR
    DASH[Dashboard<br/>Streamlit :8501] -->|/ask /search| API
    DASH -->|/inbox /vault /status| API
    DASH -->|/nachtjob/pause| API
    API[FastAPI :8080] -->|liest| VAULT[(Vault, nur lesend)]
    API -->|liest Läufe,<br/>schreibt nur pause.json| STATE[(Volume nachtjob)]
    NIGHT[Nachtjob] -->|schreibt Läufe,<br/>liest pause.json| STATE
```

- **Warum nur über die API?** So bleibt das Frontend austauschbar (React oder Blazor später) und braucht weder Chroma noch Ollama noch Schreibrechte am Vault.
- **Inbox und Statistik lesen den Vault direkt**, nicht den Index. Sie stimmen deshalb auch, wenn der Gaming-PC schläft und noch nicht alles eingebettet ist.
- **Pause per Knopf:** Der Gaming-Schutz aus Phase 3 (`assistant nightly pause`) ist jetzt auch im Dashboard. Die API schreibt dafür `pause.json` ins gemeinsame Volume, der Nachtjob liest sie vor jedem Lauf.
- **Design nur über das Theme:** Farben, Schriften, Radien und Diagrammfarben stehen in `dashboard/.streamlit/config.toml`, hell und dunkel getrennt. Keine eigenen CSS-Regeln, damit Streamlit-Updates nichts zerbrechen.

## Phase 5: Obsidian-Plugin

Das Plugin ist ein zweites Frontend neben dem Dashboard und nutzt dieselben Endpunkte (`/ask`, `/search`, `/status`).

- **`requestUrl` statt `fetch`:** Obsidian schickt die Anfrage selbst, ohne CORS. Die API braucht dafür keine Änderung, und es geht auch in der mobilen App.
- **Testbar ohne Obsidian:** Der API-Client bekommt die HTTP-Funktion hineingereicht, Textfunktionen und Einstellungen liegen in eigenen Dateien ohne Obsidian-Import. `vitest` testet sie ohne Obsidian und ohne API.
- **Ähnliche Notizen** brauchen keinen neuen Endpunkt: Titel und Anfang der aktiven Notiz (ohne Frontmatter, Code und Markdown-Zeichen) gehen als Suchtext an `/search`. `/search` liefert schon je Notiz den besten Abschnitt. Das Plugin holt einen Treffer mehr und lässt die Notiz selbst weg.
- **Quellen öffnen per `openLinkText`** mit `Pfad#Überschrift`, also wie ein normaler Wikilink: Strg/Cmd-Klick öffnet einen neuen Tab.

### Hybrid-Suche

```mermaid
flowchart LR
    Q[Frage] --> E[bge-m3<br/>Ollama] --> V[Vektorsuche<br/>Chroma]
    Q --> B[BM25<br/>im Speicher]
    V --> R[RRF<br/>1 / 60 + Platz]
    B --> R
    R --> T[beste Chunks]
```

- **Warum BM25?** Vektoren finden Umschreibungen, verfehlen aber manchmal seltene exakte Begriffe (`ITBS`, `11434`). BM25 zählt genau diese Begriffe und gewichtet seltene stärker. Eigene Umsetzung in `retrieval/bm25.py`, mit deutschen Stoppwörtern und grobem Kürzen von Endungen.
- **Warum RRF?** Kosinus-Werte (0 bis 1) und BM25-Werte (offen nach oben) lassen sich nicht direkt addieren. RRF nutzt nur die Plätze.
- **Rückfall:** Ist Ollama nicht erreichbar, sucht `hybrid` nur mit BM25 weiter. `/search` meldet das im Feld `modus`. Die Suche geht so auch, wenn der Gaming-PC schläft.
- **Der BM25-Index** wird aus den Chunks im Store gebaut, im Speicher gehalten und neu gebaut, wenn sich die Anzahl der Chunks ändert oder er älter als eine Minute ist. Eine Suche kostet so nur ein `count()`.
- **Kein Warten auf den schlafenden PC:** Vor der Vektorsuche prüft die API mit 2 s Timeout, ob Ollama antwortet, und merkt sich das Ergebnis 30 s. `assistant eval` fällt nie still auf BM25 zurück, sondern scheitert sichtbar.
- **Gemessen:** Treffer@1 95 % → 100 %, Treffer@5 bleibt 100 % (siehe [Eval-Ergebnisse](eval-ergebnisse.md)).

### Link-Erweiterung

- **Idee:** Wer in Obsidian schreibt, verlinkt Zusammenhänge selbst. Notizen, auf die die besten drei Treffer verlinken, kommen deshalb mit in die Auswahl, auch wenn sie andere Wörter benutzen als die Frage.
- **Wohin in der Liste?** Direkt hinter die besten drei Notizen, zuerst die, auf die mehrere Treffer zeigen. Eine Fusion per RRF hat im Eval Treffer@1 verschlechtert, das Einfügen lässt die ersten Plätze unverändert.
- **Links auflösen** wie Obsidian: über Pfad oder Name, ohne Groß/klein, bei gleichen Namen der kürzeste Pfad (`retrieval/links.py`). Der Link-Graph wird zusammen mit dem BM25-Index gebaut.
- **Nicht im Nachtjob:** Der verlinkt neue Notizen weiter nur mit der reinen Vektorsuche.
