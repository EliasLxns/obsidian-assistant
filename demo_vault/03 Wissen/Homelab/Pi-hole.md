---
tags: [homelab, dns, docker]
erstellt: 2026-03-08
---
# Pi-hole

Pi-hole ist der DNS-Server im Heimnetz und blockiert Werbe- und Tracking-Domains für alle Geräte.

## Betrieb

Läuft als Container in [[Compose]] auf dem Kobold. DNS braucht **Port 53** (TCP und UDP), die Weboberfläche liegt auf Port 8080, weil 80 schon belegt ist.

In der Fritzbox ist unter „Heimnetz → Netzwerk → Netzwerkeinstellungen → IPv4“ der lokale DNS-Server auf `192.168.1.10` gestellt.

## Wenn eine Seite nicht lädt

1. Im Query-Log nachsehen, welche Domain geblockt wurde.
2. Domain auf die Allowlist setzen.
3. Bei Fehlern im Container: `docker compose logs pihole`.

Siehe [[Netzwerkplan]]
