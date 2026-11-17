---
tags: [homelab, ki, ollama]
erstellt: 2026-09-14
---
# Ollama

Ollama läuft auf dem Gaming-PC „Drache“ mit der Grafikkarte und stellt lokale Sprachmodelle bereit.

## Port und Erreichbarkeit

Ollama lauscht standardmäßig auf **Port 11434**. Damit andere Geräte im Heimnetz zugreifen können, muss die Umgebungsvariable `OLLAMA_HOST=0.0.0.0` gesetzt sein, sonst hört Ollama nur auf `127.0.0.1`.

Test vom Server aus: `curl http://192.168.1.50:11434/api/tags`

## Modelle

- `ollama pull bge-m3` für Embeddings
- `ollama pull qwen2.5:7b-instruct` als Chat-Modell
- `ollama list` zeigt alle geladenen Modelle

## Strom sparen

Der Drache soll nicht durchlaufen. Er wird bei Bedarf per [[Wake-on-LAN]] geweckt und geht nach 30 Minuten ohne Last in den Ruhezustand.

Siehe [[Netzwerkplan]]
