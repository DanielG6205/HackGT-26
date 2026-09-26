"""Independent camera-space vision. No audio credentials or hardware control."""
from .models import FaceObservation, Gaze, TrackedObject, VisionFrame

__all__ = ['FaceObservation', 'Gaze', 'TrackedObject', 'VisionFrame']
