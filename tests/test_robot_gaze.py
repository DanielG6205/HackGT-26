"""Offline tests for robot calibration, protocol, and motion safety."""
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace

from app.robot import RobotController
from app.robot.gaze import GazeController, GazeMap, LABELS, load_axes, save_points


def points():
    return [dict(label=label, camera_x=.1+.4*(i%3), camera_y=.1+.4*(i//3),
                 neck_angle=86+4*(i%3), head_pitch_angle=86+4*(i//3))
            for i, label in enumerate(LABELS)]


class RobotGazeTests(unittest.TestCase):
    def setUp(self):
        self.axes = load_axes(Path(__file__).resolve().parents[1]/'config/robot-servos.example.json')
        self.robot = RobotController.mock()
        self.now = 0.
        self.gaze = GazeController(self.robot, self.axes, GazeMap(points()), clock=lambda: self.now)

    def test_protocol_and_clamped_jogs(self):
        self.gaze.initialize()
        self.assertEqual(self.robot.transport.lines[0], 'CONFIG,eyes,10,85.0000,90.0000,95.0000')
        self.assertEqual(self.robot.transport.last, 'POSE,90.0000,90.0000,90.0000')
        self.gaze.jog('neck', 999)
        self.assertEqual(self.gaze.pose['neck'], 95)
        self.gaze.jog('head', -999)
        self.assertEqual(self.gaze.pose['head'], 85)
        with self.assertRaises(ValueError):
            self.gaze.set_pose(eyes=float('nan'))
        self.gaze.center()
        self.assertEqual(list(self.gaze.pose.values()), [90]*3)

    def test_mapping_persistence_and_invalidation(self):
        mapping = GazeMap(points())
        for point in points():
            self.assertEqual(mapping.map(point['camera_x'], point['camera_y']),
                             (point['neck_angle'], point['head_pitch_angle']))
        for x in (-10, .33, 10):
            for y in (-10, .62, 10):
                self.assertTrue(all(86 <= a <= 94 for a in mapping.map(x, y)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'gaze.json'
            save_points(path, self.axes, points())
            self.assertEqual(GazeMap.load(path, self.axes).map(.5,.5), (90,90))
            changed = dict(self.axes, neck=replace(self.axes['neck'], invert=True))
            with self.assertRaises(ValueError):
                GazeMap.load(path, changed)
        with self.assertRaises(ValueError):
            GazeMap(points()[:8])
        bad = points()
        bad[1].update(camera_x=.1, camera_y=.1)
        with self.assertRaises(ValueError):
            GazeMap(bad)

    def test_eye_lead_return_and_speed(self):
        self.now = .05
        self.gaze.look_at(.9, .9)
        self.assertGreater(self.gaze.pose['eyes'], 90)
        self.assertEqual(self.gaze.pose['neck'], 90)
        for _ in range(150):
            previous = dict(self.gaze.pose)
            self.now += .02
            self.gaze.look_at(.9, .9)
            for name, angle in self.gaze.pose.items():
                self.assertLessEqual(abs(angle-previous[name]), (100 if name == 'eyes' else 30)*.02+1e-8)
                self.assertTrue(85 <= angle <= 95)
        self.assertAlmostEqual(self.gaze.pose['neck'], 94, delta=.11)
        self.assertAlmostEqual(self.gaze.pose['eyes'], 90, delta=.2)
        previous = dict(self.gaze.pose)
        self.gaze.hold()
        self.assertEqual(previous, self.gaze.pose)

    def test_inversion_and_legacy_set_bounds(self):
        self.axes['eyes'] = replace(self.axes['eyes'], invert=True)
        self.now = .05
        self.gaze.look_at(.9, .5)
        self.assertLess(self.gaze.pose['eyes'], 90)
        self.robot.set_servo('eye_x', 1000)
        self.assertEqual(self.robot.transport.last, 'SET,eye_x,120.00')
        with self.assertRaises(ValueError):
            self.robot.set_servo('head_x', 90)


if __name__ == '__main__':
    unittest.main()
