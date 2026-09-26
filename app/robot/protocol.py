"""Line-oriented command protocol between host Python and robot firmware.

Commands are ASCII, comma-separated, terminated by newline when sent on the wire.
Unknown commands should be ignored by the firmware (optionally reply ERR).

Examples:
  LOOK,0.72,0.41
  LOOK,0.72,0.41,0.50,0.55   # optional head_x, head_y
  CENTER
  EXPR,neutral
  MOVE,LEFT
  SET,eye_x,95.0
  PING
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


VALID_MOVES = frozenset({"LEFT", "RIGHT", "UP", "DOWN", "CENTER"})
VALID_AXES = frozenset({"eye_x", "eye_y", "head_x", "head_y"})


@dataclass(frozen=True)
class Command:
    name: str
    args: tuple[str, ...] = ()

    def encode(self) -> str:
        if not self.args:
            return self.name
        return self.name + "," + ",".join(self.args)


def encode_look(x: float, y: float, head_x: float | None = None, head_y: float | None = None) -> str:
    parts = ["LOOK", f"{x:.4f}", f"{y:.4f}"]
    if head_x is not None and head_y is not None:
        parts.extend([f"{head_x:.4f}", f"{head_y:.4f}"])
    return ",".join(parts)


def encode_center() -> str:
    return "CENTER"


def encode_expression(name: str) -> str:
    label = name.strip().lower().replace(" ", "_")
    if not label:
        raise ValueError("expression name must be nonempty")
    return f"EXPR,{label}"


def encode_move(direction: str) -> str:
    key = direction.strip().upper()
    if key not in VALID_MOVES:
        raise ValueError(f"direction must be one of {sorted(VALID_MOVES)}")
    return f"MOVE,{key}"


def encode_set_axis(axis: str, angle_deg: float) -> str:
    if axis not in VALID_AXES:
        raise ValueError(f"axis must be one of {sorted(VALID_AXES)}")
    return f"SET,{axis},{angle_deg:.2f}"


def encode_ping() -> str:
    return "PING"


def parse_command(line: str) -> Command:
    """Parse a protocol line into a Command (no validation of numeric ranges)."""
    text = line.strip()
    if not text:
        raise ValueError("empty command")
    parts = [p.strip() for p in text.split(",")]
    name = parts[0].upper()
    return Command(name=name, args=tuple(parts[1:]))


def format_wire(command: str) -> bytes:
    """Terminate a command for serial/Wi-Fi/BLE framing."""
    return (command.rstrip("\r\n") + "\n").encode("ascii", errors="strict")


def join_commands(commands: Sequence[str]) -> bytes:
    return b"".join(format_wire(c) for c in commands)
