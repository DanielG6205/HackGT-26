"""USB serial transport (pyserial)."""
from __future__ import annotations

from ..protocol import format_wire
from .base import Transport


class SerialTransport(Transport):
    """Send protocol lines over a USB serial port.

    Requires the optional ``pyserial`` package. Port/baud come from the caller
    (typically RobotHardwareConfig.serial_port / serial_baud).
    """

    def __init__(self, port: str, baud: int = 115200, timeout: float = 0.1):
        if not port:
            raise ValueError("serial port must be a nonempty device path")
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._serial = None

    def open(self) -> None:
        if self._serial is not None:
            return
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pyserial is required for SerialTransport; "
                "install with: python -m pip install pyserial"
            ) from exc
        self._serial = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            timeout=self.timeout,
            write_timeout=self.timeout,
        )

    def close(self) -> None:
        if self._serial is None:
            return
        try:
            self._serial.close()
        finally:
            self._serial = None

    def is_open(self) -> bool:
        return self._serial is not None and bool(getattr(self._serial, "is_open", True))

    def send_line(self, line: str) -> None:
        if not self.is_open():
            raise RuntimeError("SerialTransport is closed")
        self._serial.write(format_wire(line))
        self._serial.flush()
