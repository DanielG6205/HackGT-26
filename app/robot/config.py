"""Configurable servo mapping, motion limits, and link settings.

Pico W uses BLE for motion; microphone and speaker remain on the computer.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

TransportMode = Literal["bluetooth", "wifi", "serial", "mock", "auto"]


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

    eye_x: ServoAxisConfig = field(default_factory=lambda: ServoAxisConfig(pin=18))
    eye_y: ServoAxisConfig = field(default_factory=lambda: ServoAxisConfig(pin=19))
    head_x: ServoAxisConfig = field(
        default_factory=lambda: ServoAxisConfig(pin=21, enabled=False)
    )
    head_y: ServoAxisConfig = field(
        default_factory=lambda: ServoAxisConfig(pin=22, enabled=False)
    )
    deadzone: float = 0.02
    max_look_speed: float = 1.5
    calibration_step: float = 0.15
    couple_head_to_look: bool = False
    # Auto honors explicit legacy endpoints, otherwise connects to Pico BLE.
    transport: TransportMode = "auto"
    bluetooth_name: str = "PicoRobot"
    bluetooth_address: str = ""
    bluetooth_timeout: float = 10.0
    wifi_host: str = ""
    wifi_port: int = 9000
    wifi_timeout: float = 2.0
    serial_port: str = ""
    serial_baud: int = 115200
    serial_timeout: float = 0.1

    def __post_init__(self):
        for name in ("deadzone", "max_look_speed", "calibration_step",
                     "serial_timeout", "wifi_timeout"):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if not math.isfinite(self.bluetooth_timeout) or self.bluetooth_timeout <= 0:
            raise ValueError("bluetooth_timeout must be finite and positive")
        if self.deadzone >= 0.5:
            raise ValueError("deadzone must be < 0.5")
        if self.serial_baud <= 0:
            raise ValueError("serial_baud must be positive")
        if not 1 <= self.wifi_port <= 65535:
            raise ValueError("wifi_port must be 1–65535")
        if self.transport not in ("bluetooth", "wifi", "serial", "mock", "auto"):
            raise ValueError("transport must be bluetooth, wifi, serial, mock, or auto")

    def with_updates(self, **kwargs) -> RobotHardwareConfig:
        return replace(self, **kwargs)

    def resolved_transport(self) -> TransportMode:
        if self.transport != "auto":
            return self.transport
        if self.bluetooth_address:
            return "bluetooth"
        if self.wifi_host:
            return "wifi"
        if self.serial_port:
            return "serial"
        return "bluetooth"

    @classmethod
    def from_env(cls) -> RobotHardwareConfig:
        """Load transport overrides from .env; servo geometry stays code-configurable."""
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        base = cls()
        mode = os.getenv("ROBOT_TRANSPORT", base.transport).strip().lower() or "auto"
        if mode not in ("bluetooth", "wifi", "serial", "mock", "auto"):
            raise ValueError("ROBOT_TRANSPORT must be bluetooth, wifi, serial, mock, or auto")
        return base.with_updates(
            transport=mode,  # type: ignore[arg-type]
            bluetooth_name=os.getenv("ROBOT_BLUETOOTH_NAME", base.bluetooth_name).strip(),
            bluetooth_address=os.getenv("ROBOT_BLUETOOTH_ADDRESS", "").strip(),
            bluetooth_timeout=float(os.getenv("ROBOT_BLUETOOTH_TIMEOUT", "10")),
            wifi_host=os.getenv("ROBOT_WIFI_HOST", base.wifi_host).strip(),
            wifi_port=int(os.getenv("ROBOT_WIFI_PORT", str(base.wifi_port))),
            wifi_timeout=float(os.getenv("ROBOT_WIFI_TIMEOUT", str(base.wifi_timeout))),
            serial_port=os.getenv("ROBOT_SERIAL_PORT", base.serial_port).strip(),
            serial_baud=int(os.getenv("ROBOT_SERIAL_BAUD", str(base.serial_baud))),
        )
