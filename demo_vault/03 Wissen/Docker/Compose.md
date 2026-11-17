---
tags: [docker, compose, homelab]
erstellt: 2026-03-05
---
# Docker Compose

Alle Dienste auf dem Server „Kobold“ stehen in einer einzigen `docker-compose.yml` unter `/opt/stack`.

## Container starten und stoppen

- Alles starten (im Hintergrund): `docker compose up -d`
- Alles stoppen und entfernen: `docker compose down`
- Nur einen Dienst neu starten: `docker compose restart pihole`
- Neue Images holen und neu starten: `docker compose pull && docker compose up -d`

## Aufbau der Datei

```yaml
services:
  pihole:
    image: pihole/pihole:latest
    restart: unless-stopped
    volumes:
      - ./pihole:/etc/pihole
```

`restart: unless-stopped` sorgt dafür, dass die Container nach einem Neustart des Servers von selbst wieder hochkommen.

## Merker

Seit Compose V2 heißt der Befehl `docker compose` (mit Leerzeichen), nicht mehr `docker-compose`.

Verwandt: [[Docker Grundlagen]], [[Pi-hole]], [[Volumes und Backups]]
