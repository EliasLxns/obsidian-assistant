---
tags: [homelab, netzwerk]
erstellt: 2026-02-18
---
# Netzwerkplan

Heimnetz `192.168.1.0/24`, Router ist die Fritzbox auf `192.168.1.1`.

| Gerät | IP | Aufgabe |
|---|---|---|
| Kobold (Mini-Server) | 192.168.1.10 | Docker-Host, [[Pi-hole]], Backups |
| Drache (Gaming-PC) | 192.168.1.50 | [[Ollama]], Spiele |
| Drucker | 192.168.1.80 | – |

## DHCP

Die Fritzbox verteilt Adressen ab `.100`. Server und Gaming-PC haben feste Reservierungen, damit Wake-on-LAN und Compose-Konfigurationen stabil bleiben.

## Von unterwegs

Von außen ist kein Port offen. Zugriff nur über [[Tailscale]].
