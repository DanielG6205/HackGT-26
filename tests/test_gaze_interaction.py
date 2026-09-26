"""Deterministic object attention trials without models or a webcam."""
import unittest
from app.vision.interaction import GazeInteraction, InteractionState, OBJECT_PROMPTS
from app.vision.models import Gaze, TrackedObject


def gaze(x=0, y=0):
    return Gaze(looking_at_camera=abs(x) < .65 and abs(y) < .65,
                horizontal_score=x, vertical_score=y)


def obj(identity=4, label='bottle', x=.8, y=.2, confidence=.9):
    return TrackedObject(identity, label, confidence, (0, 0, 10, 10), (5, 5), (x, y))


class InteractionTests(unittest.TestCase):
    def make(self, **kwargs):
        messages = []
        trial = GazeInteraction(emit=messages.append, **kwargs)
        return trial, messages

    def test_streak_and_repeat(self):
        trial, messages = self.make(hold_frames=2, delay=.1)
        objects = (obj(),)
        trial.update(gaze(), 0, objects)
        trial.update(None, .1, objects)
        trial.update(gaze(), .2, objects)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_EYE_CONTACT)
        trial.update(gaze(), .3, objects)
        self.assertTrue(any('[ROBOT] ' + text.format(label='bottle') in messages
                            for text in OBJECT_PROMPTS))
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(gaze(1, -1), .4, objects)
        trial.update(gaze(-1, 0), .5, objects)
        trial.update(gaze(1, -1), .6, objects)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(gaze(1, -1), .7, objects)
        self.assertIn('[SUCCESS] User followed gaze toward bottle #4.', messages)
        self.assertEqual(messages.count('[ROBOT] Hurray!'), 1)
        trial.update(None, .9)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_EYE_CONTACT)
        self.assertIsNone(trial.target_object)

    def test_no_candidates_then_select_highest_confidence(self):
        trial, _ = self.make(hold_frames=1)
        trial.update(gaze(), 0, (obj(label='person'), obj(x=.5, y=.5), obj(identity=None)))
        self.assertIs(trial.state, InteractionState.SELECT_OBJECT)
        trial.update(gaze(), .1, (obj(confidence=.7), obj(identity=5, label='cup')))
        self.assertEqual(trial.target_object.track_id, 5)

    def test_lost_target_does_not_switch_or_succeed(self):
        trial, messages = self.make(hold_frames=2)
        trial.update(gaze(), 0, (obj(),))
        trial.update(gaze(), .1, (obj(),))
        trial.update(gaze(1, -1), .2, (obj(),))
        trial.update(gaze(1, -1), .3, (obj(identity=8),))
        trial.update(gaze(1, -1), .4, (obj(),))
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        self.assertEqual(trial.target_object.track_id, 4)
        trial.update(None, 5.1)
        self.assertIn('[TIMEOUT] User did not follow bottle #4.', messages)

    def test_moving_target_and_center_rejection(self):
        trial, _ = self.make(hold_frames=1)
        trial.update(gaze(), 0, (obj(),))
        trial.update(gaze(), .1, (obj(x=.5, y=.5),))
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(gaze(1, -1), .2, (obj(x=.2, y=.8),))
        self.assertEqual(trial.target_direction, 'SW')
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(gaze(-1, 1), .3, (obj(x=.2, y=.8),))
        self.assertIs(trial.state, InteractionState.COOLDOWN)

    def test_thresholds_invalid_gaze_and_time(self):
        trial, messages = self.make(horizontal_threshold=.8, vertical_threshold=.9)
        self.assertEqual(trial.direction_of(gaze(.8, .9)), 'CENTER')
        self.assertEqual(trial.direction_of(gaze(1, -1)), 'NE')
        for invalid in (None, Gaze(), gaze(float('nan'), 0)):
            self.assertEqual(trial.direction_of(invalid), 'UNKNOWN')
        trial.update(gaze(), 0)
        trial.update(gaze(), .1)
        trial.update(gaze(), 1)
        self.assertEqual(trial._streak, 1)
        self.assertEqual(messages.count('[GAZE] CENTER'), 1)
        with self.assertRaises(ValueError):
            trial.update(gaze(), 1)
        for options in ({'object_margin': .5}, {'hold_frames': 0}, {'timeout': -1}):
            with self.assertRaises(ValueError):
                self.make(**options)


if __name__ == '__main__':
    unittest.main()
