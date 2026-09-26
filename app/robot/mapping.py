"""Map normalized camera coordinates to servo angles."""
from __future__ import annotations

import math

from .config import ServoAxisConfig


def clamp01(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("normalized coordinate must be finite")
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def apply_deadzone(x: float, y: float, prev_x: float, prev_y: float, deadzone: float) -> bool:
    """Return True when the new target should be accepted (outside deadzone)."""
    if deadzone <= 0:
        return True
    return abs(x - prev_x) >= deadzone or abs(y - prev_y) >= deadzone


def norm_to_angle(norm: float, axis: ServoAxisConfig) -> float:
    """Map normalized 0–1 to degrees within the axis min/center/max.

    0.0 → min (or max if inverted), 0.5 → center, 1.0 → max (or min if inverted).
    Travel is piecewise-linear so asymmetric limits around center still work.
    """
    n = clamp01(norm)
    if axis.invert:
        n = 1.0 - n
    if n <= 0.5:
        t = n / 0.5
        return axis.min_deg + t * (axis.center_deg - axis.min_deg)
    t = (n - 0.5) / 0.5
    return axis.center_deg + t * (axis.max_deg - axis.center_deg)


def angle_to_norm(angle: float, axis: ServoAxisConfig) -> float:
    """Inverse of norm_to_angle for calibration display."""
    if not math.isfinite(angle):
        raise ValueError("angle must be finite")
    lo, mid, hi = axis.min_deg, axis.center_deg, axis.max_deg
    angle = lo if angle < lo else hi if angle > hi else angle
    if angle <= mid:
        n = 0.0 if mid == lo else 0.5 * (angle - lo) / (mid - lo)
    else:
        n = 1.0 if hi == mid else 0.5 + 0.5 * (angle - mid) / (hi - mid)
    return 1.0 - n if axis.invert else n


def step_toward(current: float, target: float, max_delta: float) -> float:
    """Advance current toward target by at most max_delta."""
    if max_delta < 0:
        raise ValueError("max_delta must be nonnegative")
    delta = target - current
    if abs(delta) <= max_delta:
        return target
    return current + math.copysign(max_delta, delta)
