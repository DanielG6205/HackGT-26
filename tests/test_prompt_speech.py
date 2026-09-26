"""No network/audio: exercise worker playback and trial timing."""
import threading
import unittest
from unittest.mock import Mock
from app.speech.prompts import PromptSpeaker
from app.vision.interaction import GazeInteraction, InteractionState
from app.vision.models import Gaze, TrackedObject


class PromptTests(unittest.TestCase):
    def test_only_robot_messages_are_spoken_off_thread(self):
        release = threading.Event()
        entered = threading.Event()
        def speak(text):
            entered.set()
            release.wait(2)
        service = Mock()
        service.speak.side_effect = speak
        with PromptSpeaker(service, emit=Mock()) as prompts:
            try:
                prompts('[GAZE] E')
                service.speak.assert_not_called()
                prompts('[ROBOT] Look at the bottle!')
                self.assertTrue(entered.wait(1))
                self.assertTrue(prompts.busy)
                self.assertTrue(prompts.busy)
            finally:
                release.set()
        self.assertFalse(prompts.busy)
        service.speak.assert_called_once_with('Look at the bottle!')

    def test_silent_and_failure(self):
        with PromptSpeaker(emit=Mock()) as prompts:
            prompts('[ROBOT] Look at me!')
            self.assertFalse(prompts.busy)
        service = Mock()
        service.speak.side_effect = RuntimeError('TTS failed')
        with PromptSpeaker(service, emit=Mock()) as prompts:
            prompts('[ROBOT] Look at me!')
        self.assertTrue(prompts.busy)
        with self.assertRaisesRegex(RuntimeError, 'TTS failed'):
            _ = prompts.busy

    def test_response_clock_starts_after_speech(self):
        trial = GazeInteraction(hold_frames=1, emit=Mock())
        center = Gaze(looking_at_camera=True, horizontal_score=0, vertical_score=0)
        right = Gaze(looking_at_camera=False, horizontal_score=1, vertical_score=0)
        objects = (TrackedObject(4, 'bottle', .9, (0, 0, 1, 1), (0, 0), (.8, .5)),)
        trial.update(center, 0, objects, prompt_pending=True)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_EYE_CONTACT)
        trial.update(center, 1, objects)
        trial.update(center, 1.1, objects)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(right, 8, objects, prompt_pending=True)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(right, 9, objects)
        self.assertIs(trial.state, InteractionState.WAIT_FOR_GAZE)
        trial.update(right, 9.1, objects)
        self.assertIs(trial.state, InteractionState.COOLDOWN)
