"""Offline geometry/behavior tests: no camera, model weights, or network."""
import json
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from app.vision.gaze_tracker import (
    GazeSmoother, POSE_INDICES, POSE_MODEL, estimate_head_pose, iris_offset,
)
from app.vision.models import FaceObservation, Gaze, TrackedObject, VisionFrame
from app.vision.object_tracker import ObjectTracker


class VisionTests(unittest.TestCase):
    def test_pose_camera_signs(self):
        camera = np.array([[640., 0, 320], [0, 640, 240], [0, 0, 1]])
        for rotation, expected in [((0, 0, 0), (0, 0)),
                                   ((0, -0.3, 0), (17.1887, 0)),
                                   ((-0.2, 0, 0), (0, -11.4592)),
                                   ((0.2, 0, 0), (0, 11.4592))]:
            pixels, _ = cv2.projectPoints(POSE_MODEL, np.array(rotation, dtype=float),
                                          np.array([0., 0., 600.]), camera, np.zeros(4))
            points = np.zeros((478, 2))
            points[list(POSE_INDICES)] = pixels.reshape(-1, 2) / (640, 480)
            yaw, pitch = estimate_head_pose(points, 640, 480)
            self.assertAlmostEqual(yaw, expected[0], places=3)
            self.assertAlmostEqual(pitch, expected[1], places=3)

    def test_iris_and_blink(self):
        points = np.array([(0.3, 0.4), (0.35, 0.38), (0.45, 0.38),
                           (0.5, 0.4), (0.45, 0.42), (0.35, 0.42), (0.43, 0.4)])
        offset = iris_offset(points, tuple(range(6)), 6, 640, 480)
        self.assertGreater(offset[0], 0)
        self.assertAlmostEqual(offset[1], 0)
        points[1:3, 1] = 0.399
        points[4:6, 1] = 0.401
        self.assertIsNone(iris_offset(points, tuple(range(6)), 6, 640, 480))

    def test_head_and_eyes_both_contribute(self):
        smoother = GazeSmoother(3)
        head_led = smoother.update(14, -11, (0, 0))
        self.assertEqual(head_led.horizontal, 'RIGHT')
        self.assertEqual(head_led.vertical, 'UP')
        smoother.reset()
        self.assertEqual(smoother.update(0, 0, (0.15, 0)).horizontal, 'RIGHT')
        smoother.reset()
        self.assertEqual(smoother.update(-25, 0, (0.24, 0)).horizontal, 'RIGHT')
        smoother.reset()
        self.assertTrue(smoother.update(0, 0, (0, 0)).looking_at_camera)
        smoother.update(0, 0, (0, 0))
        self.assertEqual(smoother.update(0, 0, (0.15, 0)).horizontal, 'CENTER')
        smoother.reset()
        self.assertEqual(smoother.update(0, 0, (0.15, 0)).horizontal, 'RIGHT')

    def test_sector_helper_and_json(self):
        obj = TrackedObject(4, 'bottle', 0.9, (0, 0, 10, 10), (5, 5), (0.8, 0.5))
        face = FaceObservation((0.5, 0.4), (0.3, 0.2, 0.7, 0.6), 0, 0,
                               None, None, Gaze('RIGHT', 'CENTER', False))
        frame = VisionFrame(123, (640, 480), (obj,), face)
        self.assertTrue(frame.is_user_looking_at(4))
        self.assertIsNone(frame.is_user_looking_at(99))
        self.assertIsNone(VisionFrame(124, (640, 480), (obj,)).is_user_looking_at(4))
        self.assertEqual(json.loads(json.dumps(frame.to_dict()))['coordinate_frame'], 'camera_image')

    def test_tracking_coordinates_and_stale_removal(self):
        def tensor(values):
            result = Mock()
            result.cpu.return_value.tolist.return_value = values
            return result
        tracker = ObjectTracker.__new__(ObjectTracker)
        tracker.confidence, tracker.image_size, tracker.device = 0.25, 416, 'cpu'
        boxes = Mock(xyxy=tensor([[10, 20, 90, 60]]),
                     conf=tensor([0.91]), id=tensor([4]))
        boxes.cls = tensor([0])
        result = Mock(boxes=boxes, names={0: 'bottle'})
        tracker.model = Mock()
        tracker.model.track.return_value = [result]
        tracker.update(np.zeros((100, 200, 3), dtype=np.uint8))
        self.assertEqual(tracker.get_by_id(4).center_normalized, (0.25, 0.4))
        self.assertEqual(tracker.find_best('Bottle').track_id, 4)
        boxes.id = None
        tracker.update(np.zeros((100, 200, 3), dtype=np.uint8))
        self.assertIsNone(tracker.objects[0].track_id)
        self.assertIsNone(tracker.get_by_id(None))
        result.boxes = None
        self.assertEqual(tracker.update(np.zeros((100, 200, 3), dtype=np.uint8)), ())
        self.assertIsNone(tracker.get_by_id(4))
        self.assertIsNone(tracker.find_best('bottle'))


if __name__ == '__main__':
    unittest.main()
