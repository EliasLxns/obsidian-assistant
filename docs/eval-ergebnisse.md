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
- Die drei `verlinkt`-Fragen findet BM25 auch ohne Links, weil sie gemeinsame Wörter enthalten. Mit bge-m3 sind sie in Lauf 4 gemessen.
- Der eigentliche Nutzen liegt bei echten Vaults: Dort verlinkt man Zusammenhänge, deren Notizen sich im Wortlaut wenig ähneln.

### Nachvollziehen (Lauf 3)

```bash
assistant eval --modus hybrid --details   # LINK_EXPANSION=true ist Standard
assistant eval --modus bm25 --details   # ohne Ollama; --no-links schaltet die Links ab
```

## Lauf 4: alle 23 Fragen mit bge-m3 (21.11.2026)

Stand `main` nach PR #15, Gaming-PC mit RTX 2070, `bge-m3` über Ollama, Chunks bis 1500 Zeichen mit 200 Zeichen Überlappung. Damit sind jetzt auch die drei `verlinkt`-Fragen mit Vektor und Hybrid gemessen.

| Suche | Fragen | Treffer@1 | Treffer@5 | mehrere (5) @1 |
|---|---:|---:|---:|---:|
| vektor | 23 | 96 % | 100 % | 80 % |
| hybrid | 23 | 100 % | 100 % | 100 % |
| **hybrid + Links** (Standard) | 23 | **100 %** | **100 %** | **100 %** |

Einzige Abweichung: „Was pflanze ich neben Tomaten, und wann dürfen sie ins Freie?“ steht bei reiner Vektorsuche auf Rang 2, mit Hybrid auf Rang 1 (wie schon in Lauf 2).

### Einordnung

- Hybrid + Links erfüllt die Ziele für Version 1 (Treffer@5 ≥ 80 %, Treffer@1 ≥ 50 %) deutlich, auf allen vier Fragetypen.
- Die Link-Erweiterung macht mit bge-m3 auf diesem Set keinen messbaren Unterschied, weil Hybrid schon ohne sie alle Fragen auf Rang 1 findet. Ihr Nutzen zeigt sich bisher nur im BM25-Rückfall (Lauf 3).
- **Das Eval-Set ist damit ausgereizt.** Für weitere Vergleiche braucht es ein schwereres Set: `verlinkt`-Fragen, deren zweite Notiz im Wortlaut wenig mit der Frage gemein hat, Fachbegriffe, die nur in einer Notiz stehen, und Tippfehler.

### Nachvollziehen (Lauf 4)

```bash
assistant eval --modus vektor --details
assistant eval --modus hybrid --no-links --details
assistant eval --modus hybrid --details
```

## Lauf 5: Schweres Eval-Set (21.11.2026)

Das Standard-Set ist mit Hybrid ausgereizt. Deshalb gibt es `eval/schwer.yaml` mit 30 Fragen am selben Demo-Vault:

| Typ | Fragen | Was es schwer macht |
|---|---:|---|
| umschreibung | 10 | Synonyme und Umgangssprache („Treter“, „Nacktschnecken“, „Staunässe“, „Nager“), oft mit einer Nachbarnotiz als Ablenker („Wie starte ich nur den Werbeblocker neu?“ gehört zu Compose, nicht zu Pi-hole) |
| mehrere | 9 | zwei oder drei Quellen, z. B. die Ports für DNS, Sprachmodelle und Dashboard aus drei Homelab-Notizen |
| verlinkt | 4 | die zweite Notiz teilt kaum Wörter mit der Frage, ist aber von der ersten verlinkt |
| ohne_antwort | 7 | das Thema steht im Vault, die Einzelheit nicht („Wie hoch ist mein Ruhepuls?“, nur der Maximalpuls ist notiert) |

Fragen ohne Antwort zählen nicht in Treffer@k. Der Eval zeigt für beide Gruppen den niedrigsten, mittleren und höchsten besten Score. Liegen die Gruppen getrennt, lässt sich eine Schwelle setzen, unter der der Assistent „nichts gefunden“ sagt; `--schwelle` zählt, wie viele Fragen sie richtig ablehnt und wie viele beantwortbare sie fälschlich unterdrückt.

BM25 in der Cloud (ohne Ollama), Vektor und Hybrid am Gaming-PC (RTX 2070, `bge-m3`), Chunks bis 1500 Zeichen mit 200 Überlappung. Treffer zählen nur die 23 beantwortbaren Fragen.

| Suche | Set | Treffer@1 | Treffer@5 | umschreibung @5 | mehrere @5 | verlinkt @5 |
|---|---|---:|---:|---:|---:|---:|
| hybrid + Links | Standard (23) | 100 % | 100 % | 100 % | 100 % | 100 % |
| **vektor** | **schwer** | **65 %** | **96 %** | 90 % | 100 % | 100 % |
| hybrid + Links (Standard) | schwer | 74 % | 87 % | 80 % | 89 % | 100 % |
| bm25 + Links | schwer | 57 % | 78 % | 60 % | 89 % | 100 % |
| bm25 | schwer | 57 % | 70 % | 60 % | 78 % | 75 % |

Bester Score je Frage (niedrigster / Median / höchster):

| Suche | mit Antwort | ohne Antwort | Schwelle | abgelehnt (ohne Antwort) | fälschlich unterdrückt |
|---|---|---|---:|---:|---:|
| vektor (Kosinus) | 0,455 / 0,568 / 0,739 | 0,374 / 0,492 / 0,629 | 0,5 | 4 von 7 | 3 von 23 |
| bm25 | 3,3 / 6,6 / 20,0 | 3,0 / 4,5 / 5,7 | 5 | 5 von 7 | 9 von 23 |
| hybrid (RRF) | 0,016 / 0,032 / 0,033 | 0,016 / 0,032 / 0,033 | – | nicht trennbar | |

Laufzeit am Gaming-PC: 5,8 s für den Hybrid-Lauf inklusive Laden von bge-m3, 1,7 s für Vektor.

### Einordnung

- **Das Set ist deutlich schwerer** und trennt jetzt die Suchmodi: Treffer@1 fällt überall, und Hybrid verliert erstmals gegen Vektor (87 % gegen 96 % Treffer@5). Hybrid + Links erfüllt das Ziel von 80 % trotzdem, BM25 allein knapp nicht.
- **Warum Hybrid hier schlechter ist:** RRF gibt BM25 dasselbe Gewicht wie den Vektoren. Bei Synonymen ohne gemeinsamen Wortstamm („gesichert“ ↔ „Backup“, „Treter“ ↔ „Laufschuhe“) liefert BM25 nur Rauschen, das die richtige Notiz aus den Top 5 drückt. Bei der Drei-Quellen-Frage zum Gemüsebeet fehlt so eine der drei Notizen. Vektor verpasst nur „Café-WLAN“ (Tailscale-Exit-Node). Ein nächster Versuch wäre ein Gewicht für BM25 in der Fusion, gemessen auf beiden Sets.
- **Die Link-Erweiterung hilft BM25:** ohne sie 70 %, mit ihr 78 %. Sie holt die dritte Notiz beim Halbmarathon-Aufbau und das Rennergebnis beim Tapering. Mit bge-m3 sind alle vier `verlinkt`-Fragen schon ohne sie in den Top 5.
- **„Nichts gefunden“ lässt sich noch nicht sauber erkennen.** Nur der Kosinus der Vektorsuche taugt als Schwelle; RRF-Werte hängen nur von den Plätzen ab (höchstens etwa 0,033) und sind bei beiden Gruppen gleich. Aber auch der Kosinus trennt nicht scharf: „Wie hoch ist mein Ruhepuls?“ (0,629, die Pulszonen-Notiz passt thematisch) und „Womit dünge ich die Tomaten?“ (0,568) liegen über vielen echten Treffern. Eine Schwelle von 0,5 lehnt 4 von 7 ab und kostet 3 echte Antworten. Für diese Fälle bleibt es Aufgabe des Chat-Modells, ehrlich „steht nicht in den Notizen“ zu sagen; das misst der Retrieval-Eval nicht.

### Nachvollziehen (Lauf 5)

```bash
assistant eval --fragen eval/schwer.yaml --modus bm25 --details --schwelle 5   # ohne Ollama
assistant eval --fragen eval/schwer.yaml --modus hybrid --details
assistant eval --fragen eval/schwer.yaml --modus vektor --details --schwelle 0.5   # Trennschärfe
```
