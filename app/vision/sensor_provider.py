"""Thread-safe holder for the latest vision snapshot (conversation ↔ camera)."""
from __future__ import annotations

import threading

from app.vision.context import slim_sensor_context
from app.vision.models import VisionFrame


class VisionSensorProvider:
    """Camera loop calls update(); conversation calls this as sensor_provider."""

    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot: VisionFrame | None = None

    def update(self, snapshot: VisionFrame | None) -> None:
        with self._lock:
            self._snapshot = snapshot

    def latest(self) -> VisionFrame | None:
        with self._lock:
            return self._snapshot

    def __call__(self) -> dict | None:
        with self._lock:
            return slim_sensor_context(self._snapshot)
