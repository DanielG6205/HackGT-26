"""Single-face tracking and deliberately coarse, camera-relative gaze heuristics."""
from collections import deque
from pathlib import Path
import math
import os
import tempfile
import urllib.request

import cv2
import numpy as np

from .models import FaceObservation, Gaze
from .object_tracker import MODEL_DIR

FACE_MODEL_URL = ('https://storage.googleapis.com/mediapipe-models/'
                  'face_landmarker/face_landmarker/float16/1/face_landmarker.task')
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
LEFT_EYE = (362, 385, 387, 263, 373, 380)
POSE_INDICES = (1, 152, 33, 263, 61, 291)
# Generic face, arbitrary units: image-aligned x/y; nose points toward -z.
# These are NOT measurements of the user or robot geometry.
POSE_MODEL = np.array([(0, 0, 0), (0, 63, 12), (-43, -32, 26),
                       (43, -32, 26), (-28, 28, 24), (28, 28, 24)], dtype=np.float64)


def ensure_face_model(path=None):
    target = Path(path) if path else MODEL_DIR / 'face_landmarker.task'
    if target.is_file():
        return target
    if path is not None:
        raise FileNotFoundError(f'Face model not found: {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic installation: interrupted downloads never masquerade as models.
    temporary = None
    try:
        with urllib.request.urlopen(FACE_MODEL_URL, timeout=60) as response:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                temporary = output.name
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
        os.replace(temporary, target)
    except (OSError, ValueError) as exc:
        raise RuntimeError(f'Cannot download face model; download {FACE_MODEL_URL} '
                           f'to {target} or pass --face-model') from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return target


def estimate_head_pose(points, width, height):
    """Approximate yaw +right/pitch +down; no camera extrinsics or depth output."""
    pixels = np.asarray(points, dtype=np.float64)[list(POSE_INDICES)] * (width, height)
    focal = float(max(width, height))
    camera = np.array([[focal, 0, width / 2], [0, focal, height / 2], [0, 0, 1.]])
    ok, rotation, translation = cv2.solvePnP(POSE_MODEL, pixels, camera,
                                            np.zeros(4), flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok or not np.isfinite(rotation).all() or translation[2, 0] <= 0:
        return None
    projected, _ = cv2.projectPoints(POSE_MODEL, rotation, translation, camera, np.zeros(4))
    error = np.linalg.norm(projected.reshape(-1, 2) - pixels, axis=1).mean()
    if error > max(8, np.linalg.norm(pixels[2] - pixels[3]) * 0.2):
        return None
    matrix, _ = cv2.Rodrigues(rotation)
    forward = matrix @ np.array([0., 0., -1.])
    yaw = math.degrees(math.atan2(forward[0], -forward[2]))
    pitch = math.degrees(math.atan2(forward[1], math.hypot(forward[0], forward[2])))
    if abs(yaw) > 75 or abs(pitch) > 60:
        return None
    return yaw, pitch


def iris_offset(points, indices, iris, width, height):
    """Eye-local iris displacement; handle roll, blinks, and implausible fits."""
    pixels = np.asarray(points, dtype=float) * (width, height)
    eye = pixels[list(indices)]
    left, right = sorted((eye[0], eye[3]), key=lambda p: p[0])
    axis = right - left
    span = np.linalg.norm(axis)
    if span < 6:
        return None
    horizontal = axis / span
    vertical = np.array([-horizontal[1], horizontal[0]])
    top = (eye[1] + eye[2]) / 2
    bottom = (eye[4] + eye[5]) / 2
    opening = np.dot(bottom - top, vertical)
    if opening / span < 0.12:  # Blink/squint: don't mistake closed eyelids for gaze.
        return None
    displacement = pixels[iris] - (left + right) / 2
    x = np.dot(displacement, horizontal) / span
    y = np.dot(pixels[iris] - (top + bottom) / 2, vertical) / opening
    if abs(x) > 0.45 or abs(y) > 0.65:
        return None
    # Rotate eye-local offsets back to camera image axes.
    return horizontal * x + vertical * (y * 0.3)


class GazeSmoother:
    def __init__(self, window=5):
        if window < 1:
            raise ValueError('Smoothing window must be positive')
        self.samples = deque(maxlen=window)

    def reset(self):
        self.samples.clear()

    def update(self, yaw, pitch, offset):
        # Give head orientation 25% more weight for easier head-led interaction.
        # Iris displacement can still reinforce OR counteract head orientation.
        self.samples.append((yaw / 20 + offset[0] / 0.12,
                             pitch / 16 + offset[1] / 0.09))
        x, y = np.mean(self.samples, axis=0)
        horizontal = 'LEFT' if x < -0.65 else 'RIGHT' if x > 0.65 else 'CENTER'
        vertical = 'UP' if y < -0.65 else 'DOWN' if y > 0.65 else 'CENTER'
        return Gaze(horizontal, vertical, horizontal == vertical == 'CENTER', float(x), float(y))


class GazeTracker:
    def __init__(self, model_path=None, smoothing=5):
        import mediapipe as mp
        self.mp = mp
        self.smoother = GazeSmoother(smoothing)
        path = ensure_face_model(model_path)
        options = mp.tasks.vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO, num_faces=1,
            min_face_detection_confidence=0.6, min_face_presence_confidence=0.6,
            min_tracking_confidence=0.6)
        self.landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)
        self._last_timestamp = -1
        self._last_center = None

    def update(self, frame, timestamp_ms):
        if timestamp_ms <= self._last_timestamp:
            raise ValueError('Frame timestamps must strictly increase')
        gap = timestamp_ms - self._last_timestamp
        self._last_timestamp = timestamp_ms
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.landmarker.detect_for_video(
            self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb), timestamp_ms)
        if not result.face_landmarks:
            self.smoother.reset()
            self._last_center = None
            return None
        points = tuple((float(p.x), float(p.y)) for p in result.face_landmarks[0])
        coords = np.asarray(points)
        low, high = np.clip(coords.min(axis=0), 0, 1), np.clip(coords.max(axis=0), 0, 1)
        center = tuple((low + high) / 2)
        if gap > 500 or (self._last_center is not None and
                         np.linalg.norm(np.subtract(center, self._last_center)) > 0.15):
            self.smoother.reset()
        self._last_center = center
        height, width = frame.shape[:2]
        pose = estimate_head_pose(points, width, height)
        left_iris = points[473] if len(points) >= 478 else None
        right_iris = points[468] if len(points) >= 478 else None
        offsets = [iris_offset(points, eye, iris, width, height)
                   for eye, iris in ((LEFT_EYE, 473), (RIGHT_EYE, 468))] if left_iris else []
        if pose and len(offsets) == 2 and all(o is not None for o in offsets):
            gaze = self.smoother.update(*pose, np.mean(offsets, axis=0))
        else:
            self.smoother.reset()
            gaze = Gaze()
        return FaceObservation(
            center, (*low, *high), pose[0] if pose else None, pose[1] if pose else None,
            left_iris, right_iris, gaze, points,
            tuple(points[i] for i in LEFT_EYE), tuple(points[i] for i in RIGHT_EYE))

    def close(self):
        self.landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
