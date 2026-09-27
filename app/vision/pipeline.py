"""Synchronous per-frame processing; run alongside the conversation worker."""
from .gaze_tracker import GazeTracker
from .models import VisionFrame
from .object_tracker import ObjectTracker


class VisionPipeline:
    def __init__(self, *, yolo_model=None, face_model=None, image_size=640,
                 confidence=0.25, device='auto', smoothing=5):
        self.objects = ObjectTracker(yolo_model, confidence, image_size, device)
        self.gaze = GazeTracker(face_model, smoothing)
        self._last_timestamp = -1

    def process(self, frame, timestamp_ms, *, detect_objects=True):
        if timestamp_ms <= self._last_timestamp:
            raise ValueError('Frame timestamps must strictly increase')
        self._last_timestamp = timestamp_ms
        height, width = frame.shape[:2]
        objects = self.objects.update(frame) if detect_objects else ()
        face = self.gaze.update(frame, timestamp_ms)
        return VisionFrame(timestamp_ms, (width, height), objects, face)

    def close(self):
        self.gaze.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
