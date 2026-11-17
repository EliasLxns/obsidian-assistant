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
