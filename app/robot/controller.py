"""High-level robot look / expression controller.

Vision code produces normalized camera targets; this module applies deadzone,
speed limits, optional head coupling, maps to servo angles for inspection, and
sends transport-independent protocol lines to the firmware.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from .config import RobotHardwareConfig
from .mapping import apply_deadzone, clamp01, norm_to_angle, step_toward
from .protocol import (
    encode_center,
    encode_expression,
    encode_look,
    encode_move,
    encode_ping,
    encode_set_axis,
)
from .transport.base import Transport
from .transport.mock import MockTransport
from .transport.serial_transport import SerialTransport


@dataclass(frozen=True)
class LookState:
    """Current commanded look target and mapped eye (and optional head) angles."""

    x: float
    y: float
    eye_x_deg: float
    eye_y_deg: float
    head_x_deg: float | None = None
    head_y_deg: float | None = None
    expression: str = "neutral"


class RobotController:
    """Host-side robot motion API.

    Typical wiring from vision (without modifying vision internals)::

        robot.look_at(*face.face_center)
        robot.look_at_object(tracked)
        robot.look_at_user()          # uses last cached user face center
        robot.center_eyes()
        robot.set_expression("happy")
    """

    def __init__(
        self,
        transport: Transport | None = None,
        config: RobotHardwareConfig | None = None,
        *,
        auto_open: bool = True,
        clock=time.monotonic,
    ):
        self.config = config or RobotHardwareConfig()
        self.transport = transport or MockTransport()
        self._clock = clock
        self._last_time: float | None = None
        self._target = (0.5, 0.5)
        self._commanded = (0.5, 0.5)
        self._sent: tuple[float, float] | None = None
        self._user_target: tuple[float, float] | None = None
        self._expression = "neutral"
        self._opened = False
        if auto_open:
            self.open()

    @classmethod
    def mock(cls, config: RobotHardwareConfig | None = None) -> RobotController:
        return cls(MockTransport(), config)

    @classmethod
    def serial(
        cls,
        port: str | None = None,
        config: RobotHardwareConfig | None = None,
        **kwargs,
    ) -> RobotController:
        cfg = config or RobotHardwareConfig.from_env()
        device = port or cfg.serial_port
        if not device:
            raise ValueError("Set ROBOT_SERIAL_PORT or pass port= to RobotController.serial()")
        return cls(
            SerialTransport(device, cfg.serial_baud, cfg.serial_timeout),
            cfg,
            **kwargs,
        )

    def open(self) -> None:
        if not self._opened:
            self.transport.open()
            self._opened = True

    def close(self) -> None:
        if self._opened:
            self.transport.close()
            self._opened = False

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    # --- public API ---------------------------------------------------------

    def look_at(self, x: float, y: float) -> LookState:
        """Look at a normalized camera point (0–1, +x right, +y down)."""
        self._target = (clamp01(x), clamp01(y))
        return self._tick()

    def snap_look(self, x: float, y: float) -> LookState:
        """Jump to a look target immediately (calibration / tests; no speed limit)."""
        self._target = (clamp01(x), clamp01(y))
        self._commanded = self._target
        self._last_time = self._clock()
        self._emit_look(*self._commanded)
        self._sent = self._commanded
        return self.state

    def look_at_user(self, face: Any | None = None) -> LookState:
        """Look at a face observation or the last cached user target."""
        if face is not None:
            center = getattr(face, "face_center", None)
            if center is None:
                raise TypeError("face must provide face_center=(x, y)")
            self.remember_user(center[0], center[1])
        if self._user_target is None:
            return self.center_eyes()
        return self.look_at(*self._user_target)

    def look_at_object(self, obj: Any) -> LookState:
        """Look at a TrackedObject (or any object with center_normalized)."""
        center = getattr(obj, "center_normalized", None)
        if center is None:
            raise TypeError("obj must provide center_normalized=(x, y)")
        return self.look_at(center[0], center[1])

    def center_eyes(self) -> LookState:
        self._target = (0.5, 0.5)
        self._commanded = (0.5, 0.5)
        self._sent = (0.5, 0.5)
        self._last_time = self._clock()
        self._send(encode_center())
        return self.state

    def set_expression(self, name: str) -> LookState:
        self._expression = name.strip().lower().replace(" ", "_") or "neutral"
        self._send(encode_expression(self._expression))
        return self.state

    def remember_user(self, x: float, y: float) -> None:
        """Cache a face center for later look_at_user() calls."""
        self._user_target = (clamp01(x), clamp01(y))

    def update_from_vision(self, snapshot: Any) -> None:
        """Optional helper: cache face center from a VisionFrame-like snapshot."""
        face = getattr(snapshot, "face", None)
        if face is not None:
            center = getattr(face, "face_center", None)
            if center is not None:
                self.remember_user(center[0], center[1])

    def nudge(self, direction: str) -> LookState:
        """Calibration helper: nudge look target LEFT/RIGHT/UP/DOWN or CENTER."""
        key = direction.strip().upper()
        step = self.config.calibration_step
        x, y = self._commanded
        if key == "CENTER":
            return self.center_eyes()
        if key == "LEFT":
            x -= step
        elif key == "RIGHT":
            x += step
        elif key == "UP":
            y -= step
        elif key == "DOWN":
            y += step
        else:
            raise ValueError("direction must be LEFT, RIGHT, UP, DOWN, or CENTER")
        self._send(encode_move(key))
        # Snap for responsive manual testing (bypass speed limit).
        self._target = (clamp01(x), clamp01(y))
        self._commanded = self._target
        self._last_time = self._clock()
        self._emit_look(*self._commanded)
        self._sent = self._commanded
        return self.state

    def set_servo(self, axis: str, angle_deg: float) -> None:
        """Direct angle command for range testing (bypasses look mapping)."""
        if not math.isfinite(angle_deg):
            raise ValueError("angle_deg must be finite")
        self._send(encode_set_axis(axis, angle_deg))

    def ping(self) -> None:
        self._send(encode_ping())

    def flush(self) -> LookState:
        """Advance smoothing toward the current target and send if needed."""
        return self._tick()

    @property
    def state(self) -> LookState:
        return self._build_state(*self._commanded)

    # --- internals ----------------------------------------------------------

    def _tick(self) -> LookState:
        now = self._clock()
        if self._last_time is None:
            # First command: adopt target immediately so a single look_at works.
            self._commanded = self._target
        else:
            dt = max(0.0, now - self._last_time)
            max_delta = self.config.max_look_speed * dt
            tx, ty = self._target
            cx, cy = self._commanded
            if self.config.max_look_speed <= 0:
                self._commanded = (tx, ty)
            else:
                self._commanded = (
                    step_toward(cx, tx, max_delta),
                    step_toward(cy, ty, max_delta),
                )
        self._last_time = now

        nx, ny = self._commanded
        if self._sent is None or apply_deadzone(nx, ny, self._sent[0], self._sent[1], self.config.deadzone):
            self._emit_look(nx, ny)
            self._sent = (nx, ny)
        return self.state

    def _emit_look(self, x: float, y: float) -> None:
        head_x = head_y = None
        if (
            self.config.couple_head_to_look
            and self.config.head_x.enabled
            and self.config.head_y.enabled
        ):
            head_x, head_y = x, y
        self._send(encode_look(x, y, head_x, head_y))

    def _build_state(self, x: float, y: float) -> LookState:
        cfg = self.config
        return LookState(
            x=x,
            y=y,
            eye_x_deg=norm_to_angle(x, cfg.eye_x),
            eye_y_deg=norm_to_angle(y, cfg.eye_y),
            head_x_deg=norm_to_angle(x, cfg.head_x) if cfg.head_x.enabled else None,
            head_y_deg=norm_to_angle(y, cfg.head_y) if cfg.head_y.enabled else None,
            expression=self._expression,
        )

    def _send(self, line: str) -> None:
        if not self._opened:
            self.open()
        self.transport.send_line(line)
