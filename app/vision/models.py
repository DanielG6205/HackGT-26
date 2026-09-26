"""Camera-image observations, never robot coordinates or metric 3D targets.

Unmirrored image: +x right, +y down; head yaw +right, pitch +down (degrees).
Left/right eye names are anatomical. Timestamps use the host monotonic clock.
"""
from dataclasses import asdict, dataclass, field
from typing import Literal

Horizontal = Literal['LEFT', 'CENTER', 'RIGHT', 'UNKNOWN']
Vertical = Literal['UP', 'CENTER', 'DOWN', 'UNKNOWN']
Point = tuple[float, float]


@dataclass(frozen=True)
class TrackedObject:
    track_id: int | None
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]
    center_px: Point
    center_normalized: Point


@dataclass(frozen=True)
class Gaze:
    horizontal: Horizontal = 'UNKNOWN'
    vertical: Vertical = 'UNKNOWN'
    looking_at_camera: bool | None = None
    # Smoothed heuristic scores, not angles or a 3D gaze ray.
    horizontal_score: float | None = None
    vertical_score: float | None = None


@dataclass(frozen=True)
class FaceObservation:
    face_center: Point
    bbox_normalized: tuple[float, float, float, float]
    head_yaw: float | None
    head_pitch: float | None
    left_iris: Point | None
    right_iris: Point | None
    gaze: Gaze
    landmarks: tuple[Point, ...] = ()
    left_eye: tuple[Point, ...] = ()
    right_eye: tuple[Point, ...] = ()


@dataclass(frozen=True)
class VisionFrame:
    timestamp_ms: int
    image_size: tuple[int, int]  # width, height
    objects: tuple[TrackedObject, ...] = ()
    face: FaceObservation | None = None
    coordinate_frame: str = field(default='camera_image', init=False)

    def to_dict(self):
        """JSON-serializable snapshot; tuples become arrays with json.dumps."""
        return asdict(self)

    def is_user_looking_at(self, object_id: int) -> bool | None:
        """Experimental image-sector comparison, NOT fixation detection.

        None means missing object, missing face, or unusable eyes. Use only on
        a fresh snapshot. Objects in the same image sector are indistinguishable.
        """
        obj = next((o for o in self.objects if o.track_id == object_id), None)
        if obj is None or self.face is None:
            return None
        gaze = self.face.gaze
        if gaze.looking_at_camera is None:
            return None
        x, y = obj.center_normalized
        horizontal = 'LEFT' if x < 0.4 else 'RIGHT' if x > 0.6 else 'CENTER'
        vertical = 'UP' if y < 0.4 else 'DOWN' if y > 0.6 else 'CENTER'
        return gaze.horizontal == horizontal and gaze.vertical == vertical
