# Eval-Ergebnisse

Gemessen mit `assistant eval --details` auf dem Demo-Vault (25 Notizen, 79 Chunks) und dem Eval-Set `eval/questions.yaml` (20 Fragen). Ziel für Version 1: Treffer@1 ≥ 50 %, Treffer@5 ≥ 80 %.

## Lauf 1: Embedding-Modelle im Vergleich (17.11.2026)

Umgebung: Gaming-PC (i5-13600K, RTX 2070 8 GB), Windows 11, Ollama 0.40.16, reine Vektorsuche, Chunks max. 1500 Zeichen, Überlappung 200.

| Modell | Treffer@1 | Treffer@5 | exakt (7) @1 / @5 | umschreibung (8) @1 / @5 | mehrere (5) @1 / @5 |
|---|---:|---:|---|---|---|
| **bge-m3** | **95 %** | **100 %** | 100 % / 100 % | 100 % / 100 % | 80 % / 100 % |
| nomic-embed-text | 60 % | 80 % | 100 % / 100 % | 50 % / 88 % | 20 % / 40 % |

Indexieren mit bge-m3: 79 Chunks in 87 s (erster Lauf, inklusive Laden des Modells).

### Einordnung

- **bge-m3 bleibt das Embedding-Modell.** Es erreicht beide Ziele mit Abstand; einziger Fehler auf Platz 1 ist „Was pflanze ich neben Tomaten, und wann dürfen sie ins Freie?“ (richtige Notiz auf Rang 2).
- nomic-embed-text ist bei exakten Begriffen gleichauf, verliert aber bei deutschen Umschreibungen und bei Fragen, die mehrere Notizen brauchen. Das passt dazu, dass es vor allem auf Englisch trainiert ist.
- Der Demo-Vault hat drei klar getrennte Themen und ist damit leichter als ein echter Vault. Die Zahlen sind eine Basislinie für spätere Änderungen (Hybrid-Suche, Chunking), keine Aussage über den echten Vault.

### Nachvollziehen

```bash
assistant eval --details --ausgabe eval/results/bge-m3.md
EMBED_MODEL=nomic-embed-text assistant eval --details --ausgabe eval/results/nomic-embed-text.md
```

`assistant eval` baut sich einen eigenen Index im Speicher und fasst den echten Chroma-Index nicht an; ein vorheriges `assistant index` ist nicht nötig. Die Rohausgaben je Frage landen in `eval/results/` (nicht im Repo).
