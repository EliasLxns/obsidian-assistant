---
tags: [docker, backup, homelab]
erstellt: 2026-04-11
---
# Volumes und Backups

Container sind wegwerfbar, Daten nicht. Deshalb liegen alle Daten in **Bind Mounts** unter `/opt/stack/<dienst>`.

## Backup-Routine

Jeden Sonntag um 03:30 Uhr läuft ein Cronjob mit `restic`:

1. `docker compose stop` für Dienste mit Datenbank
2. `restic backup /opt/stack` auf die externe USB-Platte „Tresor“
3. `docker compose start`

Aufbewahrung: 7 tägliche, 4 wöchentliche und 6 monatliche Snapshots (`restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6`).

## Wiederherstellen testen

Einmal im Quartal stelle ich einen Ordner testweise nach `/tmp/restore` wieder her. Ein Backup, das nie getestet wurde, zählt nicht.

Siehe auch [[Compose]], [[Netzwerkplan]]
