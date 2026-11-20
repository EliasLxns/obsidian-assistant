# Vault-Assistent – Obsidian-Plugin

Seitenleiste für Obsidian, die den Obsidian-Assistenten fragt. Das Plugin spricht nur mit der
REST-API (`/ask`, `/search`, `/status`), nie direkt mit Ollama oder dem Index.

- **Fragen**: Antwort mit Quellen. Jede Quelle ist ein `[[Name]]`-Chip und öffnet die Notiz am
  passenden Abschnitt (Strg/Cmd-Klick: neuer Tab).
- **Nur suchen**: Treffer mit Auszug, ohne Chat-Modell und deshalb schneller. Die Frage wird
  trotzdem mit `bge-m3` eingebettet, Ollama muss also erreichbar sein.
- **Ähnliche Notizen** (Befehl): sucht mit Titel und Anfang der aktiven Notiz, zeigt je Notiz
  einen Treffer und lässt die Notiz selbst weg.

Am Desktop stellt Enter die Frage (Umschalt+Enter: neue Zeile), mobil der Knopf.
- **Einstellungen**: API-Adresse (Heimnetz oder Tailscale, Standard `http://localhost:8080`),
  Anzahl Quellen, Knopf „Verbindung prüfen“.

Anfragen laufen über Obsidians `requestUrl`: kein CORS nötig, geht auch in der mobilen App.
Das Aussehen kommt nur aus Obsidians CSS-Variablen und passt sich so jedem Theme an.

## Bauen und testen

```bash
cd obsidian-plugin
npm ci
npm run typecheck   # tsc strict
npm test            # vitest, ohne Obsidian und ohne API
npm run build       # erzeugt main.js
npm run dev         # baut bei jeder Änderung neu
```

## Installieren

1. `npm run build`
2. Im Vault den Ordner `.obsidian/plugins/vault-assistent/` anlegen.
3. `main.js`, `manifest.json` und `styles.css` hineinkopieren.
4. In Obsidian unter *Einstellungen → Community-Plugins* „Vault-Assistent“ aktivieren und die
   API-Adresse eintragen.

## Aufbau

| Datei | Aufgabe |
|---|---|
| `src/api.ts` | API-Client; die HTTP-Funktion wird hineingereicht (im Plugin `requestUrl`, im Test eine Attrappe) |
| `src/text.ts` | Linkziele, Suchtext aus einer Notiz, doppelte Treffer zusammenfassen |
| `src/einstellungen.ts` | Gespeicherte Einstellungen prüfen |
| `src/view.ts` | Seitenleiste |
| `src/settings.ts` | Einstellungsseite |
| `src/main.ts` | Plugin: Ansicht, Befehle, Symbol in der Leiste |
