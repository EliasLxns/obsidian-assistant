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

### Nachvollziehen (Lauf 1)

```bash
assistant eval --details --ausgabe eval/results/bge-m3.md
EMBED_MODEL=nomic-embed-text assistant eval --details --ausgabe eval/results/nomic-embed-text.md
```

`assistant eval` baut sich einen eigenen Index im Speicher und fasst den echten Chroma-Index nicht an; ein vorheriges `assistant index` ist nicht nötig. Die Rohausgaben je Frage landen in `eval/results/` (nicht im Repo).

## Lauf 2: Vektor, BM25 und Hybrid (20.11.2026)

Gleiche Umgebung, bge-m3, Chunks max. 1500 Zeichen, Überlappung 200. Hybrid führt die Rangliste der Vektorsuche und die von BM25 per Reciprocal Rank Fusion zusammen (`score = Σ 1 / (60 + Platz)`).

| Suche | Treffer@1 | Treffer@5 | exakt (7) @1 / @5 | umschreibung (8) @1 / @5 | mehrere (5) @1 / @5 |
|---|---:|---:|---|---|---|
| **hybrid** | **100 %** | **100 %** | 100 % / 100 % | 100 % / 100 % | 100 % / 100 % |
| vektor | 95 % | 100 % | 100 % / 100 % | 100 % / 100 % | 80 % / 100 % |
| bm25 | 65 % | 85 % | 86 % / 100 % | 38 % / 75 % | 80 % / 80 % |

### Einordnung

- **Hybrid wird der Standard** (`SEARCH_MODE=hybrid`). Die Tomaten-Frage aus Lauf 1 steigt von Rang 2 auf Rang 1, sonst ändert sich nichts.
- **BM25 allein** findet exakte Begriffe zuverlässig, verliert aber bei Umschreibungen, deren Wörter so nicht in der Notiz stehen („Warum stinkt mein Komposthaufen?“, „Was wird in die unterste Lage des Gemüsebeets gefüllt?“). Als Rückfall, wenn der Gaming-PC schläft, reicht es: 85 % Treffer@5, ganz ohne Ollama.
- **Das Eval-Set ist für Vektor und Hybrid fast ausgereizt.** Für weitere Vergleiche (Link-Erweiterung, Chunking) braucht es schwerere Fragen, etwa mit Fachbegriffen, die nur in einer Notiz vorkommen, oder mit Tippfehlern.
- Der Nachtjob verlinkt weiter mit der reinen Vektorsuche, weil seine Schwelle auf Kosinus-Werte eingestellt ist. RRF-Werte sind dafür nicht vergleichbar.

### Nachvollziehen (Lauf 2)

```bash
assistant eval --modus vektor --details
assistant eval --modus hybrid --details
assistant eval --modus bm25 --details   # läuft auch ohne Ollama
```
