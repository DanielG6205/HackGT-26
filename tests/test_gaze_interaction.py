"""Deterministic trials without a camera, models, or external services."""
import unittest

from app.vision.interaction import DIRECTIONS, GazeInteraction, InteractionState
from app.vision.models import Gaze


def gaze(x=0, y=0):
    return Gaze(looking_at_camera=abs(x) < 0.65 and abs(y) < 0.65,
                horizontal_score=x, vertical_score=y)


class InteractionTests(unittest.TestCase):
    def make(self, **kwargs):
        messages = []
        trial = GazeInteraction(emit=messages.append, choose_target=lambda: 'NE', **kwargs)
        return trial, messages

    def test_compass_thresholds_and_unknown(self):
        trial, _ = self.make(horizontal_threshold=0.8, vertical_threshold=0.9)
        for direction, (x, y) in zip(DIRECTIONS, [(0, -1), (1, -1), (1, 0),
                                                 (1, 1), (0, 1), (-1, 1),
                                                 (-1, 0), (-1, -1)]):
            self.assertEqual(trial.direction_of(gaze(x, y)), direction)
        self.assertEqual(trial.direction_of(gaze(0.8, 0.9)), 'CENTER')
        for invalid in (None, Gaze(), gaze(float('nan'), 0)):
            self.assertEqual(trial.direction_of(invalid), 'UNKNOWN')

    def test_streaks_success_and_next_trial(self):
        trial, messages = self.make(hold_frames=3, delay=0.2)
        for t, sample in [(0, gaze()), (0.1, gaze()), (0.2, None),
                          (0.3, gaze()), (0.4, gaze())]:
            trial.update(sample, t)
        self.assertIs(trial.state, InteractionState.LOOK_AT_ROBOT)
        trial.update(gaze(), 0.5)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE_FOLLOW)
        self.assertEqual(trial.target_direction, 'NE')
        for t, sample in [(0.6, gaze(1, -1)), (0.7, gaze(-1, 0)),
                          (0.8, gaze(1, -1)), (0.9, gaze(1, -1))]:
            trial.update(sample, t)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE_FOLLOW)
        trial.update(gaze(1, -1), 1.0)
        self.assertIs(trial.state, InteractionState.COOLDOWN)
        self.assertIsNone(trial.target_direction)
        trial.update(gaze(), 1.1)
        self.assertIs(trial.state, InteractionState.COOLDOWN)
        trial.update(gaze(), 1.3)
        self.assertIs(trial.state, InteractionState.LOOK_AT_ROBOT)
        self.assertEqual(messages.count('[SUCCESS] User made eye contact.'), 1)
        self.assertIn('[SUCCESS] User followed gaze toward NE.', messages)
        self.assertEqual(messages.count('[ROBOT] Look at me!'), 2)

    def test_timeout_even_without_face_and_no_late_success(self):
        for last_gaze in (None, gaze(1, -1)):
            trial, messages = self.make(hold_frames=1)
            trial.update(gaze(), 0)
            trial.update(last_gaze, 5)
            self.assertIs(trial.state, InteractionState.COOLDOWN)
            self.assertIn('[TIMEOUT] User did not follow target.', messages)
            self.assertNotIn('[SUCCESS] User followed gaze toward NE.', messages)

    def test_logging_only_changes_and_capture_gap_resets_streak(self):
        trial, messages = self.make(hold_frames=3)
        trial.update(gaze(), 0)
        trial.update(gaze(), 0.1)
        trial.update(gaze(), 1)
        self.assertIs(trial.state, InteractionState.LOOK_AT_ROBOT)
        self.assertEqual(messages.count('[GAZE] CENTER'), 1)
        with self.assertRaises(ValueError):
            trial.update(gaze(), 1)

    def test_invalid_configuration(self):
        for options in ({'hold_frames': 0}, {'timeout': -1}, {'delay': -1},
                        {'horizontal_threshold': 0}, {'vertical_threshold': float('nan')}):
            with self.assertRaises(ValueError):
                self.make(**options)


if __name__ == '__main__':
    unittest.main()
