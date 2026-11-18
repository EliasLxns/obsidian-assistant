"""Wake-on-LAN: weckt den Gaming-PC und wartet, bis Ollama antwortet.

Das Magic Packet ist simpel: 6 × ``0xFF``, dann 16 × die MAC-Adresse, per UDP-Broadcast
an Port 9. Dafür braucht es keine Bibliothek. Der Container muss dafür im Netz des Hosts
laufen (``network_mode: host``), sonst erreicht der Broadcast das Heimnetz nicht.
"""

from __future__ import annotations

import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

_MAC = re.compile(r"^[0-9A-Fa-f]{2}([:-]?)(?:[0-9A-Fa-f]{2}\1){4}[0-9A-Fa-f]{2}$")


def magic_packet(mac: str) -> bytes:
    """102 Bytes: 6 × FF und 16 × die MAC. Erlaubt ``AA:BB:…``, ``AA-BB-…`` und ``AABB…``."""
    mac = mac.strip()
    if not _MAC.match(mac):
        raise ValueError(f"Ungültige MAC-Adresse: {mac!r}")
    roh = bytes.fromhex(re.sub(r"[:-]", "", mac))
    return b"\xff" * 6 + roh * 16


class Waker(Protocol):
    def wake(self) -> None: ...


class WakeOnLan:
    """Schickt das Magic Packet per UDP-Broadcast."""

    def __init__(self, mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
        self.paket = magic_packet(mac)
        self.broadcast = broadcast
        self.port = port

    def wake(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(self.paket, (self.broadcast, self.port))


class FakeWaker:
    """Für Tests: zählt nur die Weckversuche."""

    def __init__(self) -> None:
        self.gesendet = 0

    def wake(self) -> None:
        self.gesendet += 1


@dataclass(frozen=True)
class WakeResult:
    war_wach: bool  # lief Ollama schon vor dem Lauf? Dann wurde nicht geweckt
    erreichbar: bool
    gesendet: int  # Anzahl Magic Packets
    wartezeit_s: float


def wake_and_wait(
    is_awake: Callable[[], bool],
    waker: Waker | None,
    *,
    timeout_s: float = 180.0,
    intervall_s: float = 5.0,
    erneut_senden_s: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WakeResult:
    """Ist Ollama erreichbar? Wenn nicht: wecken und bis ``timeout_s`` warten.

    Das Paket wird alle ``erneut_senden_s`` Sekunden wiederholt, denn UDP kann verloren gehen.
    Ohne ``waker`` (keine MAC konfiguriert) wird nur geprüft.
    """
    if is_awake():
        return WakeResult(war_wach=True, erreichbar=True, gesendet=0, wartezeit_s=0.0)
    if waker is None:
        return WakeResult(war_wach=False, erreichbar=False, gesendet=0, wartezeit_s=0.0)

    start = clock()
    gesendet = 0
    letztes_senden = -erneut_senden_s
    while (vergangen := clock() - start) < timeout_s:
        if vergangen - letztes_senden >= erneut_senden_s:
            waker.wake()
            gesendet += 1
            letztes_senden = vergangen
        sleep(intervall_s)
        if is_awake():
            return WakeResult(False, True, gesendet, clock() - start)
    return WakeResult(False, False, gesendet, clock() - start)
