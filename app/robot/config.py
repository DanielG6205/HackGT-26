"""Configurable servo mapping and robot motion limits.

Fill pin numbers, centers, inversion, and angle limits after hardware is known.
Defaults are safe mid-range placeholders suitable for common hobby servos.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class ServoAxisConfig:
    """One servo axis: pin, center, travel limits, and optional inversion."""

    pin: int = 9
    center_deg: float = 90.0
    min_deg: float = 60.0
    max_deg: float = 120.0
    invert: bool = False
    enabled: bool = True

    def __post_init__(self):
        for name in ("center_deg", "min_deg", "max_deg"):
            value = getattr(self, name)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if not self.min_deg <= self.center_deg <= self.max_deg:
            raise ValueError("center_deg must lie within [min_deg, max_deg]")
        if not isinstance(self.pin, int) or self.pin < 0:
            raise ValueError("pin must be a nonnegative integer")


@dataclass(frozen=True)
class RobotHardwareConfig:
    """Full robot hardware and motion configuration.

    Eye axes are required for the current build. Head axes default to disabled
    so they are easy to enable later without changing the controller API.
    """

    eye_x: ServoAxisConfig = field(default_factory=lambda: ServoAxisConfig(pin=9))
    eye_y: ServoAxisConfig = field(default_factory=lambda: ServoAxisConfig(pin=10))
    head_x: ServoAxisConfig = field(
        default_factory=lambda: ServoAxisConfig(pin=5, enabled=False)
    )
    head_y: ServoAxisConfig = field(
        default_factory=lambda: ServoAxisConfig(pin=6, enabled=False)
    )
    # Ignore tiny target changes (normalized units) to reduce jitter.
    deadzone: float = 0.02
    # Max normalized units/second the host may advance the look target.
    max_look_speed: float = 1.5
    # Discrete calibration nudge in normalized units.
    calibration_step: float = 0.15
    # When True, also drive head axes toward the same look target (if enabled).
    couple_head_to_look: bool = False
    serial_port: str = ""
    serial_baud: int = 115200
    serial_timeout: float = 0.1

    def __post_init__(self):
        for name in ("deadzone", "max_look_speed", "calibration_step", "serial_timeout"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if self.deadzone >= 0.5:
            raise ValueError("deadzone must be < 0.5")
        if self.serial_baud <= 0:
            raise ValueError("serial_baud must be positive")

    def with_updates(self, **kwargs) -> RobotHardwareConfig:
        return replace(self, **kwargs)

    @classmethod
    def from_env(cls) -> RobotHardwareConfig:
        """Load transport overrides from .env; servo geometry stays code-configurable."""
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        base = cls()
        port = os.getenv("ROBOT_SERIAL_PORT", base.serial_port).strip()
        baud = int(os.getenv("ROBOT_SERIAL_BAUD", str(base.serial_baud)))
        return base.with_updates(serial_port=port, serial_baud=baud)
