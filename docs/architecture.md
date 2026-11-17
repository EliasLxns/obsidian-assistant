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
        API[FastAPI<br/>/ask /search /status /reindex]
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
2. Der Retriever kombiniert BM25 und Vektorsuche und ergänzt verlinkte Notizen.
3. Die besten Chunks gehen mit einem Prompt an das Chat-Modell in Ollama.
4. Die Antwort kommt mit Quellen als `obsidian://`-Links zurück.

## Schnittstellen im Code

`Embedder`, `VectorStore` und `LLM` sind Interfaces. Für Tests gibt es `FakeEmbedder` und `FakeLLM`, damit die Tests ohne Ollama laufen. Diese Teile entstehen in Phase 1.

## Phase 2: Dienste und inkrementelles Indexieren

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
