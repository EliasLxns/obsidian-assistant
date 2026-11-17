---
tags: [docker, homelab, grundlagen]
erstellt: 2026-03-02
---
# Docker Grundlagen

Docker verpackt eine Anwendung mit allen Abhängigkeiten in ein **Image**. Aus einem Image startet ein **Container**, also ein laufender, isolierter Prozess.

## Wichtige Befehle

- `docker ps` zeigt laufende Container, `docker ps -a` auch gestoppte.
- `docker logs -f <name>` folgt den Logs eines Containers.
- `docker exec -it <name> sh` öffnet eine Shell im Container.
- `docker image prune` räumt ungenutzte Images auf.

## Image vs. Container

Ein Image ist schreibgeschützt und wird in Schichten (Layern) gebaut. Alles, was ein Container zur Laufzeit schreibt, geht beim Löschen verloren, außer es liegt in einem Volume. Siehe [[Volumes und Backups]].

Mehrere Container zusammen verwalte ich nicht einzeln, sondern mit [[Compose]].
