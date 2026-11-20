# Demo-Video: Checkliste fürs Aufnehmen

Gehört zum [Drehbuch](drehbuch.md). Grundregel: **Im Bild ist nur der Demo-Vault.** Keine echten Notizen, keine echten IP- oder MAC-Adressen, keine Laufwerks- oder Benutzerpfade, keine Rechner- oder Benutzernamen. Die fiktiven Werte aus dem Demo-Vault (z. B. „Kobold“, `192.168.1.10`) dürfen zu sehen sein.

## 1. Eigene Demo-Umgebung aufbauen (einmalig, ca. 20 Min.)

Der echte Stack und sein Index bleiben unangetastet. Für die Aufnahme gibt es eine zweite, getrennte Kopie.

- [ ] Echten Stack anhalten, damit die Ports frei sind: im normalen Repo-Ordner `docker compose stop`.
- [ ] Repo in einen eigenen Ordner klonen, z. B. `obsidian-assistant-demo`. Compose benennt Container und Volumes nach dem Ordner, deshalb bekommt die Demo ihren eigenen Index und ihren eigenen Nachtjob-Zustand.
- [ ] Den Demo-Vault **aus dem Klon heraus kopieren** in einen eigenen Ordner namens `demo_vault` (nicht im Klon arbeiten, der Nachtjob legt ein Git-Repo im Vault an).
- [ ] Im Klon `cp .env.example .env` und nur das anpassen:
  - `VAULT_HOST_PATH=<Pfad zur Kopie>/demo_vault`
  - `VAULT_NAME=demo_vault` (muss zum Namen des Vaults in Obsidian passen, sonst öffnen die Quellen-Links nichts)
  - `GAMING_PC_MAC` leer lassen (kein Wake-on-LAN, der PC ist ja an)
- [ ] `docker compose --profile nachtjob up -d --build`, dann `curl localhost:8080/status`: `chunks` > 0, `ollama_erreichbar: true`, `vault: demo_vault`.
- [ ] In Obsidian **„Ordner als Vault öffnen“** → die Kopie `demo_vault`. Den echten Vault in diesem Fenster nicht öffnen.
- [ ] Plugin bauen und in den Demo-Vault legen: `cd obsidian-plugin && npm ci && npm run build`, dann `main.js`, `manifest.json`, `styles.css` nach `demo_vault/.obsidian/plugins/vault-assistent/`. Plugin aktivieren, API-Adresse `http://localhost:8080`, „Verbindung prüfen“.

## 2. Inbox für den Nachtjob vorbereiten

Der Nachtjob lässt Notizen liegen, die in den letzten 30 Minuten geändert wurden. Frisch kopierte Dateien zählen als „gerade geändert“.

- [ ] Entweder mindestens 30 Minuten zwischen Kopieren und Szene 4 einplanen
- [ ] oder die Änderungszeit der Inbox-Notizen zurücksetzen (PowerShell, im Demo-Vault):
  ```powershell
  Get-ChildItem "00 Inbox\*.md" | ForEach-Object { $_.LastWriteTime = (Get-Date).AddHours(-2) }
  ```
- [ ] Probelauf ohne Schreiben: `docker compose exec nachtjob assistant nightly --probelauf --jetzt`. Zeigt, in welchen Ordner die Feuchtesensor-Notiz käme. Landet sie in `Prüfen`, Szene 4 so lassen und im Sprechtext erwähnen, dass unsichere Fälle zum Prüfen liegen bleiben.
- [ ] **Für jede Wiederholung von Szene 4:** `docker compose exec nachtjob assistant nightly rueckgaengig`, danach wieder die Änderungszeit zurücksetzen (siehe oben).

## 3. Bildschirm aufräumen (Datenschutz)

- [ ] Benachrichtigungen aus (Windows: „Nicht stören“), Discord, Messenger, Mail, Spiele-Launcher schließen.
- [ ] Taskleiste automatisch ausblenden, Desktop-Symbole ausblenden, neutrales Hintergrundbild.
- [ ] **Terminal:** neutraler Prompt ohne Benutzer, Rechnername und Pfad, z. B. in PowerShell `function prompt { "PS> " }`. Fenstertitel prüfen (zeigt oft den Pfad). Den Befehlsverlauf vorher leeren oder nur neue Befehle tippen.
- [ ] **Browser:** eigenes, leeres Profil oder Gastfenster, keine Lesezeichenleiste, keine anderen Tabs, keine Erweiterungssymbole. Nur `localhost`-Adressen in der Adresszeile.
- [ ] Beim ersten Klick auf einen Quellen-Chip fragt der Browser „Obsidian öffnen?“. In der Probe einmal mit „Immer erlauben“ bestätigen, damit der Dialog nicht ins Video kommt.
- [ ] **Obsidian:** nur das Demo-Fenster offen. Vault-Wechsler unten links nicht aufklappen (er listet alle Vaults). Keine Sync-Einstellungen, kein Konto-Menü öffnen. Datei-Explorer von Windows nicht zeigen (Pfadleiste).
- [ ] **Dashboard „System“:** unten steht `Vault demo_vault · API http://api:8080`. Kontrollieren, dass dort nichts anderes steht.
- [ ] Docker-Desktop-Fenster nicht zeigen (listet auch die echten Container und Pfade).
- [ ] Nach der Aufnahme das ganze Video einmal in Ruhe durchsehen, Standbild für Standbild bei den Übergängen.

## 4. Technik

- [ ] Aufnahme mit OBS Studio (kostenlos): 1920 × 1080, 30 fps, MP4 (oder MKV und danach remuxen). Nur das Bildschirmfenster aufnehmen, nicht den ganzen Desktop, wenn möglich.
- [ ] Anzeige auf 125–150 % skalieren oder in Browser und Obsidian mit Strg + Plus vergrößern, damit Text auch auf dem Handy lesbar ist.
- [ ] Helles Theme in Obsidian und im Dashboard (liest sich in Videos besser), Szene 5 darf kurz das dunkle zeigen.
- [ ] Mikrofon: Headset reicht, Rauschunterdrückung in OBS an, Pegel um −12 dB. Ton am besten getrennt aufnehmen und über das Bild legen (Sprechtext ohne Hektik, Bildschirm ohne Erklären).
- [ ] **Aufwärmen:** Kurz vor der Aufnahme eine Frage stellen, damit `bge-m3` und das Chat-Modell schon im VRAM sind. Der erste Aufruf nach dem Start dauert deutlich länger.
- [ ] Antwortzeit einer Frage messen und für die Einblendung in Szene 2 notieren.
- [ ] Gaming-PC: kein Spiel im Hintergrund, Lüfter-/RGB-Software egal, Steam/League geschlossen.

## 5. Schnitt und Veröffentlichung

- [ ] Schneiden z. B. mit DaVinci Resolve oder Clipchamp. Wartezeiten kürzen und als „(gekürzt)“ markieren.
- [ ] Einblendungen: „Demo-Vault mit fiktiven Notizen“ (ganz), „Lauf von Hand gestartet, sonst um 3 Uhr“ (Szene 4), Antwortzeit (Szene 2).
- [ ] Untertitel auf Deutsch (der Sprechtext aus dem Drehbuch ist schon fertig), viele schauen ohne Ton.
- [ ] Hochladen als **„Nicht gelistet“** auf YouTube (oder als Datei an einem GitHub-Release). Kein Hinweis auf den echten Vault in Titel oder Beschreibung.
- [ ] Vorschaubild (Standbild aus Szene 2) als `docs/bilder/demo-video.png` speichern und den Abschnitt **Demo-Video** in der README mit dem Link füllen.
- [ ] Danach: Demo-Stack stoppen (`docker compose down` im Klon), echten Stack wieder starten.
