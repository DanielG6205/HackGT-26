"""Slim, LLM-friendly sensor snapshots from VisionFrame."""
from __future__ import annotations

from .models import VisionFrame


def slim_sensor_context(snapshot: VisionFrame | None, *, max_objects: int = 8) -> dict | None:
    """Compact vision summary for the brain (no landmark clouds)."""
    if snapshot is None:
        return None
    objects = []
    for obj in snapshot.objects:
        if len(objects) >= max_objects:
            break
        objects.append({
            "id": obj.track_id,
            "label": obj.label,
            "confidence": round(float(obj.confidence), 2),
            "center": [round(obj.center_normalized[0], 3),
                       round(obj.center_normalized[1], 3)],
        })
    ctx: dict = {
        "coordinate_frame": snapshot.coordinate_frame,
        "image_size": list(snapshot.image_size),
        "objects": objects,
    }
    face = snapshot.face
    if face is not None:
        ctx["face"] = {
            "center": [round(face.face_center[0], 3), round(face.face_center[1], 3)],
            "gaze": {
                "horizontal": face.gaze.horizontal,
                "vertical": face.gaze.vertical,
                "looking_at_camera": face.gaze.looking_at_camera,
            },
            "head_yaw": face.head_yaw,
            "head_pitch": face.head_pitch,
        }
    return ctx
