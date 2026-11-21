# Demo-Video: Drehbuch und Sprechtext

Ziel: ein Video von **etwa 2:30 Minuten**, das in einem Bewerbungsgespräch oder in der README zeigt, was der Assistent kann und wie er gebaut ist. Gezeigt wird nur der Demo-Vault (`demo_vault/`), nie ein echter Vault.

Vorbereitung und Aufnahme: [aufnahme-checkliste.md](aufnahme-checkliste.md).

## Überblick

| # | Szene | Zeit | Länge | Bild |
|---|---|---|---:|---|
| 1 | Einstieg | 0:00–0:15 | 15 s | Titelbild, dann Obsidian mit dem Demo-Vault |
| 2 | Frage mit Quellen | 0:15–0:50 | 35 s | Dashboard, Seite „Fragen“, Klick auf einen Quellen-Chip |
| 3 | Obsidian-Plugin | 0:50–1:15 | 25 s | Obsidian, Seitenleiste „Vault-Assistent“ |
| 4 | Nachtjob und Inbox | 1:15–1:55 | 40 s | Obsidian-Inbox, Terminal, sortierte Notiz, Protokoll |
| 5 | Dashboard | 1:55–2:20 | 25 s | Seiten „Inbox“, „Vault“, „System“ |
| 6 | Aufbau und Abschluss | 2:20–2:40 | 20 s | Architekturbild, Eval-Tabelle, Repo-Link |

Gesprochen wird in Ich-Form, ruhig und ohne Fachwort-Gewitter: Wer das Video sieht, soll nach dem ersten Satz wissen, was das Projekt tut, und erst danach, wie. Rund 330 Wörter, das passt bei ruhigem Tempo (etwa 130 Wörter pro Minute) in 2:30.

---

## Szene 1: Einstieg (0:00–0:15)

**Bild:** Titelbild „Obsidian-Assistent · lokaler KI-Assistent für Notizen“ (2 s), dann Obsidian mit dem geöffneten Demo-Vault, Dateibaum mit `03 Wissen/Docker`, `Garten`, `Laufen` ausgeklappt.

**Sprechtext:**

> Ich schreibe viel in Obsidian, aber finde Dinge oft nicht wieder. Deshalb habe ich einen Assistenten gebaut, der meinen Vault durchsucht, Fragen mit Quellen beantwortet und nachts die Inbox aufräumt. Alles läuft bei mir zu Hause. Keine Cloud-KI, keine Daten außer Haus.

**Einblendung** unten, die ganze Zeit über: „Demo-Vault mit fiktiven Notizen“.

## Szene 2: Frage mit Quellen (0:15–0:50)

**Bild:**
1. Browser mit dem Dashboard, Seite **Fragen**.
2. Frage eintippen: `Wie starte ich meine Container?` → **Fragen**.
3. Antwort erscheint, darunter die Quellen als `[[Wikilink]]`-Chips (erwartet: `Compose`).
4. Maus kurz auf den Score der Quelle, dann Klick auf den Chip `Compose` → Obsidian öffnet die Notiz am passenden Abschnitt.

**Sprechtext:**

> Ich frage zum Beispiel: Wie starte ich meine Container? Das Wort „Compose“ kommt in der Frage gar nicht vor. Die Suche kombiniert deshalb zwei Verfahren: eine Vektorsuche, die die Bedeutung versteht, und eine klassische Stichwortsuche für exakte Begriffe. Ein lokales Sprachmodell formuliert daraus die Antwort, und zwar nur aus meinen Notizen. Jede Aussage hat eine Quelle, und ein Klick öffnet die Notiz direkt in Obsidian, genau an der richtigen Stelle.

**Schnitt:** Wartezeit auf die Antwort im Schnitt auf etwa 2 s kürzen und mit „(gekürzt)“ einblenden, damit es ehrlich bleibt. Die echte Dauer kurz als Einblendung zeigen, z. B. „Antwort in 8 s“ (vorher messen).

## Szene 3: Obsidian-Plugin (0:50–1:15)

**Bild:**
1. In Obsidian die Seitenleiste **Vault-Assistent** öffnen.
2. Frage eintippen: `Was hilft gegen Schnecken im Beet?` → Enter.
3. Antwort mit Chips, Klick auf `Schnecken abwehren`.
4. Notiz `Tomaten` öffnen, Befehlspalette (Strg+P) → **Ähnliche Notizen zur aktuellen Notiz** → Liste mit `Mischkultur`, `Hochbeet anlegen` o. ä.

**Sprechtext:**

> Damit ich dafür nicht den Browser brauche, gibt es ein Obsidian-Plugin in TypeScript. Es sitzt in der Seitenleiste und spricht mit derselben API wie das Dashboard. Praktisch ist auch der Befehl „Ähnliche Notizen“: Zu der Notiz, die gerade offen ist, findet er verwandte Notizen, die ich vielleicht verlinken sollte.

## Szene 4: Nachtjob und Inbox (1:15–1:55)

**Bild:**
1. Obsidian, Ordner `00 Inbox`: zwei Notizen, `Idee Feuchtesensor` (ohne Tags) und `Frage Gel beim Halbmarathon`.
2. Terminal (neutraler Prompt, siehe Checkliste): `docker compose exec nachtjob assistant nightly --jetzt`. Ausgabe kurz stehen lassen.
3. Zurück in Obsidian: `Idee Feuchtesensor` liegt jetzt in einem Wissensordner, hat Tags im Frontmatter und einen Abschnitt `## Verwandt` mit Wikilinks.
4. `Frage Gel beim Halbmarathon` öffnen: unten `## Antwort des Assistenten` mit Quellen-Links.
5. Kurz das Protokoll in `00 Inbox/Protokoll` zeigen.

**Sprechtext:**

> Neue Gedanken landen bei mir erst einmal in der Inbox. Nachts weckt der Assistent meinen Gaming-PC per Wake-on-LAN, weil dort die Grafikkarte für das Sprachmodell steckt. Dann vergibt er Tags, verlinkt verwandte Notizen und sortiert die Notiz in einen passenden Ordner. Notizen, die mit „Frage“ beginnen, bekommen über Nacht eine Antwort mit Quellen. Bestehende Notizen fasst die KI nie an. Vor jedem Lauf gibt es einen Git-Commit, jeder Lauf schreibt ein Protokoll, und mit einem Befehl lässt sich alles rückgängig machen.

**Hinweis:** Für die Aufnahme wird der Lauf mit `--jetzt` von Hand gestartet. Ehrlich einblenden: „Lauf von Hand gestartet, sonst um 3 Uhr“. In welchen Ordner das Modell die Feuchtesensor-Notiz legt (Garten oder Homelab), vorher im Probelauf prüfen und den Sprechtext nicht darauf festlegen.

## Szene 5: Dashboard (1:55–2:20)

**Bild:**
1. Dashboard, Seite **Inbox**: letzter Lauf mit allen Aktionen, Kasten **Gaming-Schutz** mit „Pausieren“ (nur zeigen, nicht klicken, oder klicken und danach „Pause aufheben“).
2. Seite **Vault**: Notizen, Ordner, häufigste Tags, tote Links.
3. Seite **System**: API erreichbar, Ollama wach, Modelle, Index.

**Sprechtext:**

> Im Dashboard sehe ich, was der Nachtjob getan hat und was ich noch prüfen sollte. Wenn ich abends noch spielen will, pausiere ich ihn mit einem Klick, auch vom Handy. Dazu gibt es eine Statistik über den Vault, zum Beispiel tote Links, und den Systemstatus: Ist der Gaming-PC wach, welche Modelle laufen, wie groß ist der Index.

## Szene 6: Aufbau und Abschluss (2:20–2:40)

**Bild:**
1. Architekturbild aus [docs/architecture.md](../architecture.md) (Mermaid, als Bild exportiert) oder das ASCII-Bild aus der README.
2. Tabelle aus [docs/eval-ergebnisse.md](../eval-ergebnisse.md).
3. Endbild: Repo-Adresse `github.com/EliasLxns/obsidian-assistant`, Stichworte „Python · FastAPI · ChromaDB · Ollama · Streamlit · TypeScript“.

**Sprechtext:**

> Gebaut ist das in Python, bewusst ohne Frameworks wie LangChain, damit ich jeden Schritt selbst verstehe. FastAPI, ChromaDB und Ollama laufen in Docker. Ob die Suche gut ist, messe ich mit einem eigenen Testset: Jede Änderung an Suche oder Modell wird damit geprüft. Code, Tests und Messwerte liegen offen auf GitHub.

**Vor der Aufnahme prüfen:** Zahlen in der Einblendung nur aus dem aktuellen Stand von `docs/eval-ergebnisse.md` übernehmen, nicht aus dem Gedächtnis.

---

## Ersatzfragen

Falls eine Frage in der Probe schlecht aussieht, diese gehen auch mit dem Demo-Vault (alle im Eval-Set):

| Frage | Erwartete Quelle |
|---|---|
| Welchen Port nutzt Ollama? | `Homelab/Ollama` |
| Was bedeutet restart: unless-stopped? | `Docker/Compose` |
| Was ist ITBS? | `Laufen/Läuferknie` |
| Wie hilft ein Schneckenkragen? | `Garten/Schnecken abwehren` |

## Kurzfassung (30 s, optional)

Für LinkedIn oder als Vorschau in der README: Szene 2 (Frage, Antwort, Klick auf die Quelle) und Szene 4 Schritt 3 (sortierte Notiz), ohne Ton, mit Untertiteln. Als GIF unter 10 MB lässt es sich direkt in die README einbinden.
