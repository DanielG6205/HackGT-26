"""Transport-independent link to the robot firmware."""
from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    """Byte/line sink used by RobotController. Implementations must be thread-aware
    enough for single-writer use from the controller (no multi-writer required).
    """

    @abstractmethod
    def open(self) -> None:
        """Establish the connection. Idempotent if already open."""

    @abstractmethod
    def close(self) -> None:
        """Release the connection. Safe to call when already closed."""

    @abstractmethod
    def send_line(self, line: str) -> None:
        """Send one protocol command (without requiring a trailing newline)."""

    @abstractmethod
    def is_open(self) -> bool:
        ...

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
