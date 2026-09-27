"""Synthetic frames exercise the shape-independent calibration marker."""
import unittest
import cv2
import numpy as np
from app.robot.gaze_calibrate import green_marker


class MarkerTests(unittest.TestCase):
    def test_circle_and_rectangle(self):
        for shape in ('circle', 'rectangle'):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            if shape == 'circle':
                cv2.circle(frame, (320, 240), 35, (0, 255, 0), -1)
            else:
                cv2.rectangle(frame, (260, 220), (380, 260), (0, 255, 0), -1)
            self.assertEqual(green_marker(frame).center_normalized, (.5, .5))

    def test_ambiguity_and_small_distractors(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(frame, (320, 240), 35, (0, 255, 0), -1)
        cv2.circle(frame, (80, 80), 8, (0, 255, 0), -1)
        self.assertEqual(green_marker(frame).center_normalized, (.5, .5))
        cv2.circle(frame, (80, 80), 35, (0, 255, 0), -1)
        self.assertIsNone(green_marker(frame))

    def test_wrong_colors_empty_and_clipped(self):
        for color in ((255, 0, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)):
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.circle(frame, (320, 240), 40, color, -1)
            self.assertIsNone(green_marker(frame))
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.circle(frame, (0, 240), 40, (0, 255, 0), -1)
        self.assertIsNone(green_marker(frame))
