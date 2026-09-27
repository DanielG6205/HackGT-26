"""Approximate camera-relative angles, not calibrated 3D fixation measurements."""
import math
from dataclasses import dataclass


def separation(a, b):
    """Great-circle distance between yaw/pitch directions in degrees."""
    ay, ap = map(math.radians, a)
    by, bp = map(math.radians, b)
    dot = math.sin(ap) * math.sin(bp) + math.cos(ap) * math.cos(bp) * math.cos(ay - by)
    return math.degrees(math.acos(max(-1., min(1., dot))))


@dataclass(frozen=True)
class AngularGaze:
    horizontal_fov: float = 60
    tolerance: float = 12
    center_tolerance: float = 18
    yaw_offset: float = 0
    pitch_offset: float = 0
    head_yaw_offset: float = 0
    head_pitch_offset: float = 0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in vars(self).values()):
            raise ValueError('Gaze angle settings must be finite')
        if not 1 < self.horizontal_fov < 179 or not 0 < self.tolerance < 90:
            raise ValueError('Invalid camera FOV or gaze tolerance')
        if not 0 < self.center_tolerance < 90:
            raise ValueError('Invalid center tolerance')

    def gaze(self, gaze):
        if gaze is None or gaze.looking_at_camera is None:
            return None
        yaw, pitch = gaze.yaw_deg, gaze.pitch_deg
        # Compatibility for observations produced by older trackers.
        if yaw is None or pitch is None:
            if gaze.horizontal_score is None or gaze.vertical_score is None:
                return None
            yaw, pitch = gaze.horizontal_score * 20, gaze.vertical_score * 16
        if not math.isfinite(yaw) or not math.isfinite(pitch):
            return None
        return yaw - self.yaw_offset, pitch - self.pitch_offset

    def head(self, face):
        """Independent pose cue: iris compensation must not cancel a head turn."""
        if face is None:
            return None
        angles = face.head_yaw, face.head_pitch
        if any(value is None or not math.isfinite(value) for value in angles):
            return None
        return angles[0] - self.head_yaw_offset, angles[1] - self.head_pitch_offset

    def attention_cues(self, gaze, head):
        return tuple(name for name, angles in (('gaze', gaze), ('head', head))
                     if angles is not None and separation(angles, (0, 0)) <= self.center_tolerance)

    def matching_cues(self, gaze, head, target):
        """Either cue may count, but neutral directions and absent targets cannot."""
        if target is None or self.centered(target):
            return ()
        return tuple(name for name, angles in (('gaze', gaze), ('head', head))
                     if angles is not None and not self.centered(angles)
                     and separation(angles, target) <= self.tolerance)

    def target(self, obj, image_size):
        x, y = obj.center_normalized
        width, height = image_size
        focal = width / (2 * math.tan(math.radians(self.horizontal_fov / 2)))
        dx, dy = (x - .5) * width, (y - .5) * height
        return (math.degrees(math.atan2(dx, focal)),
                math.degrees(math.atan2(dy, math.hypot(focal, dx))))

    def centered(self, angles):
        return angles is not None and separation(angles, (0, 0)) <= self.center_tolerance
