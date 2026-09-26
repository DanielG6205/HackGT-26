"""In-memory transport for tests and dry runs without hardware."""
from __future__ import annotations

from ..protocol import format_wire
from .base import Transport


class MockTransport(Transport):
    def __init__(self):
        self.lines: list[str] = []
        self.raw: list[bytes] = []
        self._open = False

    def open(self) -> None:
        self._open = True

    def close(self) -> None:
        self._open = False

    def is_open(self) -> bool:
        return self._open

    def send_line(self, line: str) -> None:
        if not self._open:
            raise RuntimeError("MockTransport is closed")
        text = line.rstrip("\r\n")
        self.lines.append(text)
        self.raw.append(format_wire(text))

    def clear(self) -> None:
        self.lines.clear()
        self.raw.clear()

    @property
    def last(self) -> str | None:
        return self.lines[-1] if self.lines else None
