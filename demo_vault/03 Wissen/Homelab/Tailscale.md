---
tags: [homelab, netzwerk, vpn]
erstellt: 2026-05-07
---
# Tailscale

Tailscale baut ein privates Mesh-VPN auf WireGuard-Basis. So erreiche ich den Kobold von unterwegs, ohne einen Port im Router zu öffnen.

## Einrichtung

- Auf dem Kobold: `curl -fsSL https://tailscale.com/install.sh | sh` und dann `sudo tailscale up`
- Auf dem Handy die App installieren und mit demselben Konto anmelden.

## MagicDNS

Mit MagicDNS heißt der Server im Tailnet einfach `kobold`. Das Dashboard ist dann unter `http://kobold:8501` erreichbar.

## Exit Node

Der Kobold ist als Exit Node freigegeben (`tailscale up --advertise-exit-node`). Im öffentlichen WLAN läuft der Verkehr dann über das Heimnetz und damit auch über [[Pi-hole]].

Siehe [[Netzwerkplan]]
