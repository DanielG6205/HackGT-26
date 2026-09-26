"""Wi-Fi / ESP32 transport placeholder.

When hardware switches from USB serial to TCP/UDP (or WebSocket) over Wi-Fi,
implement connect/send against the same Transport interface. RobotController
does not need to change.
"""
from __future__ import annotations

from .base import Transport


class WifiTransport(Transport):
    """Placeholder for a future ESP32/Wi-Fi link.

    Expected later shape (not implemented):
      - host/port or URL from config
      - TCP line protocol reusing the same ASCII commands
      - optional reconnect / heartbeat via PING
    """

    def __init__(self, host: str = "", port: int = 9000):
        self.host = host
        self.port = port
        self._open = False

    def open(self) -> None:
        raise NotImplementedError(
            "WifiTransport is a placeholder. Configure SerialTransport for now, "
            f"or implement TCP/UDP to {self.host}:{self.port} later."
        )

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def send_line(self, line: str) -> None:
        raise NotImplementedError("WifiTransport is not implemented yet")
