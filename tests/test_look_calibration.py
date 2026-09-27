import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.vision.look_calibration import LookCalibration
from app.vision.models import FaceObservation, Gaze, TrackedObject, VisionFrame
from app.conversation.joint_attention import JointAttentionSession


def samples(inverted=False):
    sign = -1 if inverted else 1
    points = {'center': (5, 3), 'up': (5, -17), 'down': (5, 23),
              'left': (5-sign*20, 3), 'right': (5+sign*20, 3)}
    return {key: [{'head': point, 'gaze': point} for _ in range(20)] for key, point in points.items()}


def face(yaw, pitch, eyes=True):
    return FaceObservation((.5, .5), (0, 0, 1, 1), yaw, pitch, None, None,
                           Gaze(looking_at_camera=False, yaw_deg=yaw, pitch_deg=pitch, eyes_tracked=eyes))


class CalibrationTests(unittest.TestCase):
    def test_center_edges_and_inversion(self):
        for inverse in (False, True):
            calibration = LookCalibration(samples(inverse))
            self.assertTrue(calibration.centered(face(5, 3)))
            self.assertTrue(calibration.centered(face(11, 3)))
            right = calibration.points(face(-15 if inverse else 25, 3))['head']
            self.assertAlmostEqual(right[0], .95)
            self.assertAlmostEqual(right[1], .5)
            self.assertAlmostEqual(calibration.points(face(5, -17))['head'][1], .05)

    def test_reject_stationary_samples_and_unavailable_channels(self):
        with self.assertRaises(ValueError):
            LookCalibration({key: [{'head': (0, 0), 'gaze': None}] * 20 for key in samples()})
        data = samples()
        for entries in data.values():
            for entry in entries:
                entry['gaze'] = None
        calibration = LookCalibration(data)
        self.assertEqual(set(calibration.channels), {'head'})
        self.assertEqual(calibration.points(None), {})

    def test_general_pixel_direction_head_only_success_and_lost_target(self):
        calibration = LookCalibration(samples())
        phone = TrackedObject(1, 'cell phone', .9, (480, 210, 560, 270), (520, 240), (.8125, .5))
        observation = face(19, 3, eyes=False)
        self.assertEqual(calibration.matching_cues(observation, phone, (640, 480)), ('head',))
        self.assertEqual(calibration.matching_cues(observation, None, (640, 480)), ())
        self.assertEqual(calibration.matching_cues(face(-15, 3), phone, (640, 480)), ())
        with tempfile.TemporaryDirectory() as directory:
            session = JointAttentionSession(Mock(), Path(directory) / 'name.json', hold_frames=3)
            session.pixel_calibration = calibration
            session.active = True
            session.target = phone
            session.enter('LOOK')
            messages = []
            for i in range(3):
                session.update(VisionFrame(1000+i*100, (640, 480), (phone,), observation),
                               busy=False, emit=messages.append)
            self.assertEqual(messages, ['[ROBOT] Hurray!'])
