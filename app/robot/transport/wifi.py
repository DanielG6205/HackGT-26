"""TCP Wi-Fi transport for ESP32 / Wi-Fi robot link.

Same ASCII line protocol as USB serial (LOOK / CENTER / …). The board runs a
TCP server; this host is the TCP client.
"""
from __future__ import annotations

import socket
import time

from ..protocol import format_wire
from .base import Transport


class WifiTransport(Transport):
    """Send protocol lines over a TCP socket to the robot Wi-Fi chip."""

    def __init__(
        self,
        host: str,
        port: int = 9000,
        timeout: float = 2.0,
        *,
        reconnect: bool = True,
        connect_retries: int = 5,
        retry_delay: float = 0.5,
    ):
        if not host:
            raise ValueError("wifi host must be a nonempty hostname or IP")
        if not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("wifi port must be 1–65535")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reconnect = reconnect
        self.connect_retries = max(1, connect_retries)
        self.retry_delay = max(0.0, retry_delay)
        self._sock: socket.socket | None = None

    def open(self) -> None:
        if self._sock is not None:
            return
        last_exc: Exception | None = None
        for attempt in range(1, self.connect_retries + 1):
            try:
                sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sock.settimeout(self.timeout)
                self._sock = sock
                return
            except OSError as exc:
                last_exc = exc
                if attempt < self.connect_retries:
                    time.sleep(self.retry_delay)
        raise ConnectionError(
            f"Wi-Fi robot unreachable at {self.host}:{self.port} "
            f"after {self.connect_retries} tries: {last_exc}"
        ) from last_exc

    def close(self) -> None:
        sock, self._sock = self._sock, None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def is_open(self) -> bool:
        return self._sock is not None

    def send_line(self, line: str) -> None:
        if not self.is_open():
            raise RuntimeError("WifiTransport is closed")
        payload = format_wire(line)
        try:
            self._sock.sendall(payload)
        except OSError:
            if not self.reconnect:
                raise
            self.close()
            self.open()
            self._sock.sendall(payload)

    def recv_line(self, timeout: float | None = None) -> str | None:
        """Optional: read one reply line (e.g. PONG). Returns None on timeout."""
        if not self.is_open():
            raise RuntimeError("WifiTransport is closed")
        old = self._sock.gettimeout()
        if timeout is not None:
            self._sock.settimeout(timeout)
        try:
            chunks: list[bytes] = []
            while True:
                try:
                    byte = self._sock.recv(1)
                except socket.timeout:
                    return None
                if not byte:
                    return None
                if byte in (b"\n", b"\r"):
                    if chunks:
                        break
                    continue
                chunks.append(byte)
                if len(chunks) > 200:
                    break
            return b"".join(chunks).decode("ascii", errors="replace").strip()
        finally:
            self._sock.settimeout(old)
