---
tags: [homelab, netzwerk, strom]
erstellt: 2026-09-20
---
# Wake-on-LAN

Mit Wake-on-LAN (WoL) weckt der Server „Kobold“ den Gaming-PC „Drache“ über ein **Magic Packet** an dessen MAC-Adresse.

## Einrichtung

1. Im BIOS „Wake on LAN“ bzw. „Power on by PCI-E“ aktivieren.
2. In Windows im Geräte-Manager bei der Netzwerkkarte „Gerät kann den Computer aus dem Ruhezustand aktivieren“ und „Nur Magic Packet“ anhaken.
3. Schnellstart in Windows ausschalten, sonst klappt das Wecken aus dem heruntergefahrenen Zustand oft nicht.

## Wecken

`wakeonlan AA:BB:CC:11:22:33` vom Kobold aus. Danach dauert es etwa 25 Sekunden, bis [[Ollama]] antwortet.

## Fehlersuche

Wacht der PC nicht auf, liegt es fast immer am Schnellstart oder an einem Switch, der Broadcasts filtert. Siehe [[Netzwerkplan]].
