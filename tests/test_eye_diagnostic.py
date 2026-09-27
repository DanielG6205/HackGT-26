import unittest
from types import SimpleNamespace
from app.vision.eye_diagnostic import EyeDiagnostic
from app.vision.models import Gaze


class EyeDiagnosticTests(unittest.TestCase):
    def test_head_only_never_counts_as_eyes(self):
        status, angles = EyeDiagnostic().update(SimpleNamespace(gaze=Gaze(
            looking_at_camera=False, yaw_deg=30, pitch_deg=0)))
        self.assertIn('EYES UNAVAILABLE', status)
        self.assertIsNone(angles)

    def test_eye_tracking_independent_of_head_pose_and_neutral(self):
        diagnostic = EyeDiagnostic()
        face = SimpleNamespace(gaze=Gaze(eyes_tracked=True, eye_yaw_deg=5, eye_pitch_deg=-3))
        self.assertIn('HEAD POSE UNAVAILABLE', diagnostic.update(face)[0])
        diagnostic.calibrate()
        for _ in range(20):
            status, angles = diagnostic.update(face)
        self.assertEqual(angles, (0, 0))
        face.gaze = Gaze(eyes_tracked=True, eye_yaw_deg=15, eye_pitch_deg=-1)
        self.assertEqual(diagnostic.update(face)[1], (10, 2))

    def test_face_loss_resets_pending_calibration(self):
        diagnostic = EyeDiagnostic()
        diagnostic.calibrate()
        face = SimpleNamespace(gaze=Gaze(eyes_tracked=True, eye_yaw_deg=5, eye_pitch_deg=1))
        diagnostic.update(face)
        self.assertIsNone(diagnostic.update(None)[1])
        self.assertEqual(diagnostic.samples, [])
