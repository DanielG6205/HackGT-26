"""Eye-only diagnostics; never silently substitute head pose for iris tracking."""
import math


class EyeDiagnostic:
    def __init__(self):
        self.neutral = (0., 0.)
        self.samples = None

    def calibrate(self):
        self.samples = []

    def update(self, face):
        if face is None:
            if self.samples is not None:
                self.samples.clear()
            return 'NO FACE: move into view', None
        gaze = face.gaze
        eyes = gaze.eye_yaw_deg, gaze.eye_pitch_deg
        if not gaze.eyes_tracked or any(v is None or not math.isfinite(v) for v in eyes):
            if self.samples is not None:
                self.samples.clear()
            return 'EYES UNAVAILABLE: blink, occlusion, or landmarks rejected', None
        if self.samples is not None:
            self.samples.append(eyes)
            if len(self.samples) >= 20:
                self.neutral = tuple(sum(p[i] for p in self.samples) / len(self.samples) for i in (0, 1))
                self.samples = None
            else:
                return f'CALIBRATING {len(self.samples)}/20: look at camera, keep head still', eyes
        relative = tuple(v - baseline for v, baseline in zip(eyes, self.neutral))
        status = ('EYES TRACKED; HEAD POSE UNAVAILABLE' if gaze.yaw_deg is None
                  else 'EYES TRACKED')
        return status, relative
