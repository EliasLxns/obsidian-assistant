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

## Lauf 3: Link-Erweiterung (21.11.2026)

Gleiche Umgebung. Die Link-Erweiterung setzt Notizen, auf die die besten drei Treffer per Wikilink verweisen, direkt hinter diese drei (siehe `retrieval/links.py`). Die ersten Plätze ändern sich dadurch nie.

Zuerst probiert: die verlinkten Notizen als dritte Rangliste in die RRF-Fusion geben. Das hat mit BM25 Treffer@1 von 65 % auf 45 % gedrückt, weil schon kleine Zusatzpunkte die knappen Abstände der ersten Plätze umdrehen. Deshalb das Einfügen hinter den besten Treffern.

Das Eval-Set hat drei neue Fragen vom Typ `verlinkt`: Die zweite Notiz ist über einen Wikilink der ersten erreichbar (`tests/test_demo_vault.py` prüft den Link).

| Suche | Fragen | Treffer@1 | Treffer@5 | mehrere (5) @5 |
|---|---:|---:|---:|---:|
| hybrid (bge-m3) | 20 | 100 % | 100 % | 100 % |
| hybrid + Links (bge-m3) | 20 | 100 % | 100 % | 100 % |
| bm25 | 23 | 65 % | 87 % | 80 % |
| **bm25 + Links** | 23 | **65 %** | **91 %** | **100 %** |

### Einordnung

- **Die Link-Erweiterung ist ab jetzt an** (`LINK_EXPANSION=true`). Mit Hybrid ändert sie auf diesem Set nichts, es ist schon bei 100 %. Im Rückfall ohne Ollama findet sie die zweite Notiz bei „Knieprobleme und harte Einheiten“ (Läuferknie → Intervalltraining), die BM25 allein verpasst.
- Die drei `verlinkt`-Fragen findet BM25 auch ohne Links, weil sie gemeinsame Wörter enthalten. Mit bge-m3 sind sie noch nicht gemessen; das holt der nächste Lauf auf dem Gaming-PC nach.
- Der eigentliche Nutzen liegt bei echten Vaults: Dort verlinkt man Zusammenhänge, deren Notizen sich im Wortlaut wenig ähneln.

### Nachvollziehen (Lauf 3)

```bash
assistant eval --modus hybrid --details   # LINK_EXPANSION=true ist Standard
assistant eval --modus bm25 --details   # ohne Ollama; --no-links schaltet die Links ab
```

## Lauf 4: Schweres Eval-Set, erst nur BM25 (21.11.2026)

Das Standard-Set ist mit Hybrid ausgereizt. Deshalb gibt es `eval/schwer.yaml` mit 30 Fragen am selben Demo-Vault:

| Typ | Fragen | Was es schwer macht |
|---|---:|---|
| umschreibung | 10 | Synonyme und Umgangssprache („Treter“, „Nacktschnecken“, „Staunässe“, „Nager“), oft mit einer Nachbarnotiz als Ablenker („Wie starte ich nur den Werbeblocker neu?“ gehört zu Compose, nicht zu Pi-hole) |
| mehrere | 9 | zwei oder drei Quellen, z. B. die Ports für DNS, Sprachmodelle und Dashboard aus drei Homelab-Notizen |
| verlinkt | 4 | die zweite Notiz teilt kaum Wörter mit der Frage, ist aber von der ersten verlinkt |
| ohne_antwort | 7 | das Thema steht im Vault, die Einzelheit nicht („Wie hoch ist mein Ruhepuls?“, nur der Maximalpuls ist notiert) |

Fragen ohne Antwort zählen nicht in Treffer@k. Der Eval zeigt für beide Gruppen den niedrigsten, mittleren und höchsten besten Score. Liegen die Gruppen getrennt, lässt sich eine Schwelle setzen, unter der der Assistent „nichts gefunden“ sagt; `--schwelle` zählt, wie viele Fragen sie richtig ablehnt und wie viele beantwortbare sie fälschlich unterdrückt.

Gemessen in der Cloud, nur BM25 (ohne Ollama). Vektor und Hybrid mit bge-m3 holt der nächste Lauf am Gaming-PC nach.

| Suche | Set | Treffer@1 | Treffer@5 | umschreibung @5 | mehrere @5 | verlinkt @5 |
|---|---|---:|---:|---:|---:|---:|
| bm25 + Links | Standard (23) | 65 % | 91 % | 75 % | 100 % | 100 % |
| bm25 + Links | **schwer (23 + 7)** | **57 %** | **78 %** | 60 % | 89 % | 100 % |
| bm25 | schwer (23 + 7) | 57 % | 70 % | 60 % | 78 % | 75 % |

Bester BM25-Score: mit Antwort 3,3 bis 20,0 (Median 6,6), ohne Antwort 3,0 bis 5,7 (Median 4,5). Eine Schwelle von 5 lehnt 5 von 7 Fragen ohne Antwort ab, unterdrückt aber 9 von 23 beantwortbaren.

### Einordnung

- **Das Set ist schwerer:** BM25 fällt bei Treffer@5 von 91 % auf 78 % und liegt damit knapp unter dem Ziel von 80 %. Ganz verfehlt werden vor allem Synonyme ohne gemeinsamen Wortstamm („Nacktschnecken“ ↔ „Schnecken“, „Treter“, „gesichert“ ↔ „Backup“, „Regenwasser“ ↔ „Regentonne“). Genau dafür sind die Vektoren da; der Lauf am PC zeigt, ob Hybrid hier noch Luft hat.
- **Die Link-Erweiterung zahlt sich hier aus:** ohne sie 70 %, mit ihr 78 %. Sie holt die dritte Notiz beim Halbmarathon-Aufbau und das Rennergebnis beim Tapering.
- **BM25-Scores taugen nicht als Schwelle:** Die Gruppen überlappen stark, weil BM25-Werte von der Länge der Frage abhängen. Für „nichts gefunden“ kommt nur der Kosinus der Vektorsuche infrage (`--modus vektor --schwelle …`). Der Nachtjob nutzt dort schon 0,5.

### Nachvollziehen (Lauf 4)

```bash
assistant eval --fragen eval/schwer.yaml --modus bm25 --details --schwelle 5   # ohne Ollama
assistant eval --fragen eval/schwer.yaml --modus hybrid --details              # am Gaming-PC
assistant eval --fragen eval/schwer.yaml --modus vektor --schwelle 0.5         # Trennschärfe
```
