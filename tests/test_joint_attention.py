"""Offline end-to-end session transitions, using real motion protocol output."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from app.conversation.joint_attention import JointAttentionSession
from app.robot.controller import RobotController
from app.robot.look_mapping import LookMapping
from app.vision.models import FaceObservation, Gaze, TrackedObject, VisionFrame


def obj(label='cell phone', ident=1, x=.8):
    return TrackedObject(ident, label, .95, (0, 0, 1, 1), (0, 0), (x, .5))


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'name.json'
        self.session = JointAttentionSession(Mock(), self.path, hold_frames=3, timeout=5)
        self.robot = RobotController.mock()
        self.messages = []
        self.now = 1000

    def frame(self, direction='CENTER', objects=None, busy=False, advance=100):
        self.now += advance
        face = None
        if direction is not None:
            x = {'CENTER': 0, 'E': 1, 'W': -1}[direction]
            face = FaceObservation((.5, .5), (0, 0, 1, 1), x * 20, 0, None, None,
                                   Gaze(looking_at_camera=direction == 'CENTER',
                                        horizontal_score=x, vertical_score=0))
        snapshot = VisionFrame(self.now, (640, 480),
                               (obj(),) if objects is None else tuple(objects), face)
        self.session.update(snapshot, busy=busy,
                            emit=lambda value: self.messages.append('[ROBOT] ' + value() if callable(value) else value),
                            robot=self.robot)

    def start(self):
        self.assertEqual(self.session.handle('Hi Ottis'), "Hi I'm Ottis, what's your name?")
        self.assertEqual(self.session.handle('My name is Maya'), 'Maya, correct?')
        self.assertFalse(self.path.exists())
        self.session.handle('yes')

    def question(self):
        self.start()
        for _ in range(4):
            self.frame()
        self.assertEqual(self.session.phase, 'ANSWER')

    def test_find_object_prompt_and_visual_success(self):
        self.session.find_object = True
        self.start()
        for _ in range(4):
            self.frame()
        self.assertEqual(self.session.phase, 'LOOK')
        self.assertIn('Can you find the phone?', self.messages[-1])
        self.session.brain.respond.assert_not_called()
        for _ in range(4):
            self.frame('E', busy=True)
        self.assertEqual(self.session.phase, 'LOOK')
        for _ in range(3):
            self.frame('E')
        self.assertEqual(self.session.phase, 'BACK')
        self.assertEqual(self.messages[-1], '[ROBOT] Hurray!')

    def test_silent_until_wake_and_persistent_confirmed_name(self):
        self.assertIsNone(self.session.handle('hello'))
        for _ in range(5):
            self.frame('E')
        self.assertEqual(self.messages, [])
        self.start()
        self.assertEqual(json.loads(self.path.read_text()), {'name': 'Maya'})
        restored = JointAttentionSession(Mock(), self.path)
        self.assertEqual(restored.name, 'Maya')
        self.assertEqual(restored.handle('Ottis'), "Hi I'm Ottis, what's your name?")

    def test_full_cycle_answers_before_gaze_and_selects_different_object(self):
        self.question()
        self.assertEqual(self.messages, ['[ROBOT] Thanks for looking at me!',
                                         '[ROBOT] Do you know what a phone is?'])
        for _ in range(5):
            self.frame('E')
        self.assertEqual(self.session.phase, 'ANSWER')
        self.assertIn('Can you look at the phone?', self.session.handle('yes')())
        for _ in range(5):
            self.frame('E', busy=True)
        self.assertEqual(self.session.phase, 'LOOK')
        self.assertGreater(self.robot.state.x, .5)
        for _ in range(3):
            self.frame('E')
        self.assertEqual(self.session.phase, 'BACK')
        self.assertEqual(self.messages[-1], '[ROBOT] Hurray!')
        self.frame('E')
        self.assertEqual(self.messages[-1], '[ROBOT] Can you look back at me?')
        for _ in range(3):
            self.frame()
        self.frame(objects=[obj(), obj('book', 2, .2)])
        self.assertEqual(self.messages[-1], '[ROBOT] Do you know what a book is?')

    def test_object_question_tracks_target_before_answer_without_scoring(self):
        self.robot.config = self.robot.config.with_updates(max_look_speed=0, deadzone=0)
        self.question()
        self.frame('E')
        self.assertEqual(self.session.phase, 'ANSWER')
        self.assertGreater(self.robot.state.x, .5)
        self.assertNotIn('[ROBOT] Hurray!', self.messages)
        self.frame('E', objects=[obj(x=.7)])
        self.assertAlmostEqual(self.robot.state.x, .7)
        reply = self.session.handle('I use it to call my friends')()
        self.assertIn('Can you look at the phone?', reply)
        self.assertEqual(self.session.phase, 'LOOK')

    def test_bottle_only_selection_repeated_rounds_and_ambiguity(self):
        self.session.target_label = 'bottle'
        self.session.active = True
        self.session.enter('SELECT')
        self.frame(objects=[obj('book', 1), obj('bottle', 2)])
        self.assertEqual(self.session.target.label, 'bottle')
        self.assertEqual(self.session.phase, 'ANSWER')
        self.frame(objects=[obj('book', 1, .2), obj('bottle', 2, .8)])
        self.assertGreater(self.robot.state.x, .5)
        self.session.enter('SELECT')
        self.frame(objects=[obj('bottle', 2)])
        self.assertEqual(self.session.phase, 'ANSWER')
        self.session.enter('SELECT')
        self.frame(objects=[obj('bottle', 2), obj('bottle', 3)])
        self.assertEqual(self.session.phase, 'SELECT')

    def test_object_mode_never_aims_at_face_or_replacement_object(self):
        self.session.object_game = True
        self.session.active = True
        self.robot = Mock()
        self.session.enter('NAME')
        self.frame('E')
        self.robot.look_at.assert_not_called()
        self.robot.hold.assert_called_once()
        self.session.target = obj('book', 12, .8)
        self.session.enter('LOOK')
        self.frame('W', objects=[obj('book', 12, .7), obj('bottle', 9, .2)])
        self.robot.look_at.assert_called_once_with(.7, .5)
        self.robot.reset_mock()
        self.frame('W', objects=[obj('book', 99, .2)])
        self.robot.look_at.assert_not_called()
        self.robot.hold.assert_called_once()
        self.session.target = None
        self.session.enter('BACK')
        self.robot.reset_mock()
        self.frame('E')
        self.robot.look_at.assert_not_called()

    def test_requested_object_game_sequence_and_repeat(self):
        self.session.object_game = True
        for words in ('hello', 'Ottis', 'lets play'):
            self.assertIsNone(self.session.handle(words))
        self.frame('E')
        self.assertEqual(self.messages, [])
        self.assertFalse(self.session.active)
        self.assertIn("what's your name", self.session.handle('Hi Ottis'))
        self.assertIn('Can you look at me?', self.session.handle('My name is Maya'))
        self.assertEqual(json.loads(self.path.read_text()), {'name': 'Maya'})
        self.assertEqual(self.session.phase, 'ATTENTION')
        self.assertIsNone(self.session.handle('tell me a story'))
        self.assertEqual(self.session.phase, 'ATTENTION')
        self.frame('E', advance=6000)
        self.assertTrue(self.session.active)
        for _ in range(4):
            self.frame()
        self.assertEqual(self.session.phase, 'ANSWER')
        self.assertIn('Do you know what a phone is?', self.messages[-1])
        self.assertGreater(self.robot.state.x, .5)
        self.assertIn('Can you look at the phone?', self.session.handle('To call people')())
        for _ in range(4):
            self.frame('E', busy=True)
        self.assertEqual(self.session.phase, 'LOOK')
        for _ in range(3):
            self.frame('E')
        self.assertEqual(self.session.phase, 'BACK')
        self.assertIn('Good job, Maya!', self.messages[-1])
        for _ in range(4):
            self.frame()
        self.assertEqual(self.session.phase, 'ANSWER')
        self.assertEqual(self.session.target.label, 'cell phone')
        self.assertIn('Do you know what a phone is?', self.messages[-1])

    def test_object_selection_requires_fresh_consistent_detection(self):
        from dataclasses import replace
        self.session.object_game = True
        self.session.object_confirmation_frames = 3
        self.session.active = True
        self.session.enter('SELECT')
        self.robot = Mock()
        weak = replace(obj('cup', 3), confidence=.30)
        for _ in range(5):
            self.frame(objects=[weak])
        self.assertIsNone(self.session.target)
        self.assertEqual(self.messages, [])
        self.frame(objects=[obj('book', 5)])
        self.frame(objects=[obj('book', 5)])
        self.frame(objects=[])  # Lost detection resets confirmation.
        self.frame(objects=[obj('book', 5)])
        self.frame(objects=[obj('book', 5)])
        self.assertIsNone(self.session.target)
        self.robot.look_at.assert_not_called()
        self.frame(objects=[obj('book', 5)])
        self.assertEqual(self.session.target.label, 'book')
        self.robot.look_at.assert_called_once_with(.8, .5)
        self.assertIn('book', self.messages[-1])

    def test_question_cannot_substitute_cup_for_selected_book(self):
        self.session.object_game = True
        self.session.brain.respond.return_value = 'What color is the cup?'
        self.assertEqual(self.session.ask_about_object('book'), 'What do you use a book for?')

    def test_only_prompts_attention_when_observed_off_center(self):
        self.start()
        self.frame(None)
        self.frame()
        self.assertEqual(self.messages, [])
        self.frame('E')
        self.assertEqual(self.messages, ['[ROBOT] Can you look at me?'])
        self.frame('E')
        self.assertEqual(len(self.messages), 1)

    def test_lost_face_target_center_and_frame_gaps_cannot_succeed(self):
        self.question()
        self.session.handle('I do not know')
        self.frame('E')
        self.frame('E')
        self.frame('E', advance=2100)
        self.assertEqual(self.session.phase, 'LOOK')
        for direction, objects in [(None, [obj()]), ('E', []), ('CENTER', [obj(x=.5)])]:
            for _ in range(3):
                self.frame(direction, objects)
            self.assertEqual(self.session.phase, 'LOOK')
        self.assertNotIn('[ROBOT] Hurray!', self.messages)

    def test_stop_and_no_answer_timeout_return_to_wake_gate(self):
        self.question()
        self.frame(advance=6000)
        self.frame(advance=6000)
        self.assertFalse(self.session.active)
        before = len(self.messages)
        self.frame('E')
        self.assertEqual(len(self.messages), before)
        self.assertIsNone(self.session.handle('yes'))
        self.session.handle('Ottis')
        self.session.handle('stop')
        self.assertFalse(self.session.active)

    def test_no_return_attention_prompt_if_already_centered(self):
        self.question()
        self.session.handle('yes')
        for _ in range(3):
            self.frame('E')
        for _ in range(3):
            self.frame('CENTER')
        self.assertEqual(self.session.phase, 'SELECT')
        self.assertFalse(any('look back' in message for message in self.messages))

    def test_calibration_inversion_offsets_and_clamping(self):
        mapping = LookMapping(x_gain=-1, y_gain=.5, x_offset=.1)
        x, y = mapping.apply(.8, .9)
        self.assertAlmostEqual(x, .3)
        self.assertAlmostEqual(y, .7)
        self.assertEqual(LookMapping(x_gain=2).apply(1, .5), (1, .5))
        with self.assertRaises(ValueError):
            LookMapping(x_gain=float('nan'))

class AngleTests(unittest.TestCase):
    def test_leftward_eye_offset_stays_left_and_center_allows_small_drift(self):
        from app.vision.gaze_tracker import GazeSmoother
        gaze = GazeSmoother(1).update(0, 0, (-.12, 0))
        self.assertEqual(gaze.horizontal, 'LEFT')
        centered = GazeSmoother(1).update(14, 0)
        self.assertTrue(centered.looking_at_camera)

    def test_center_angular_tolerance_includes_small_drift(self):
        from app.vision.angles import AngularGaze
        self.assertTrue(AngularGaze().centered((10, 0)))

    def test_continuous_matching_across_old_sector_boundary(self):
        from app.vision.angles import AngularGaze, separation
        angles = AngularGaze()
        gaze = Gaze(looking_at_camera=False, yaw_deg=20, pitch_deg=10.5)
        target = angles.target(obj(), (640, 480))
        self.assertLess(separation(angles.gaze(gaze), target), angles.tolerance)
        # Same old right-hand sector, but much too far from this target.
        far = Gaze(looking_at_camera=False, yaw_deg=60, pitch_deg=0)
        self.assertGreater(separation(angles.gaze(far), target), angles.tolerance)

    def test_iris_contributes_even_with_turned_head(self):
        from app.vision.gaze_tracker import GazeSmoother
        gaze = GazeSmoother(1).update(20, 0, (-.12, 0))
        self.assertTrue(gaze.eyes_tracked)
        self.assertAlmostEqual(gaze.yaw_deg, 0)
        head_only = GazeSmoother(1).update(20, 0)
        self.assertFalse(head_only.eyes_tracked)
        self.assertAlmostEqual(head_only.yaw_deg, 20)

    def test_neutral_offsets_and_unknown(self):
        from app.vision.angles import AngularGaze
        angles = AngularGaze(yaw_offset=7, pitch_offset=-4)
        self.assertEqual(angles.gaze(Gaze(looking_at_camera=True, yaw_deg=7, pitch_deg=-4)), (0, 0))
        self.assertIsNone(angles.gaze(Gaze()))
        with self.assertRaises(ValueError):
            AngularGaze(tolerance=0)

    def test_console_shows_target_angles_and_missing_face(self):
        with tempfile.TemporaryDirectory() as directory:
            session = JointAttentionSession(Mock(), Path(directory) / 'name.json')
            session.active = True
            session.target = obj()
            session.enter('LOOK')
            frame = VisionFrame(1000, (640, 480), (obj(),), None)
            with self.assertLogs('app.conversation.joint_attention', level='INFO') as logs:
                session.update(frame, busy=False, emit=lambda _: None)
            output = logs.output[0]
            self.assertIn('requested=phone #1', output)
            self.assertIn('yaw=', output)
            self.assertIn('gaze unavailable', output)
            self.assertIn('hold=0/5', output)


class HeadAttentionTests(unittest.TestCase):
    def run_trial(self, head_yaw, gaze_yaw, *, missing_target=False, busy=False):
        with tempfile.TemporaryDirectory() as directory:
            session = JointAttentionSession(Mock(), Path(directory) / 'name.json', hold_frames=3)
            session.active = True
            session.target = obj()
            session.enter('LOOK')
            gaze = Gaze(looking_at_camera=gaze_yaw == 0, yaw_deg=gaze_yaw, pitch_deg=0,
                        eyes_tracked=gaze_yaw is not None)
            face = FaceObservation((.5, .5), (0, 0, 1, 1), head_yaw, 0, None, None, gaze)
            messages = []
            for i in range(3):
                session.update(VisionFrame(1000 + i * 100, (640, 480),
                                           () if missing_target else (obj(),), face),
                               busy=busy, emit=messages.append)
            return messages

    def test_head_turn_succeeds_when_iris_compensates_to_center(self):
        self.assertIn('[ROBOT] Hurray!', self.run_trial(20, 0))

    def test_eye_led_turn_still_succeeds_with_neutral_head(self):
        self.assertIn('[ROBOT] Hurray!', self.run_trial(0, 20))

    def test_head_turn_succeeds_when_iris_unavailable(self):
        self.assertIn('[ROBOT] Hurray!', self.run_trial(20, None))

    def test_wrong_head_direction_missing_target_and_speech_do_not_succeed(self):
        for kwargs in ({'head_yaw': -20, 'gaze_yaw': 0},
                       {'head_yaw': 20, 'gaze_yaw': 0, 'missing_target': True},
                       {'head_yaw': 20, 'gaze_yaw': 0, 'busy': True},
                       {'head_yaw': float('nan'), 'gaze_yaw': 0}):
            with self.subTest(kwargs=kwargs):
                self.assertNotIn('[ROBOT] Hurray!', self.run_trial(**kwargs))


class ReturnAttentionTests(unittest.TestCase):
    def test_head_center_accepts_biased_iris_and_missing_face_never_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            session = JointAttentionSession(Mock(), Path(directory) / 'name.json', hold_frames=3)
            session.active = True
            session.enter('BACK')
            face = FaceObservation((.5, .5), (0, 0, 1, 1), 4, 5, None, None,
                                   Gaze(looking_at_camera=False, yaw_deg=25, pitch_deg=15))
            messages = []
            for i in range(2):
                session.update(VisionFrame(1000+i*100, (640, 480), (), face),
                               busy=False, emit=messages.append)
            self.assertEqual(session.streak, 2)
            session.update(VisionFrame(1200, (640, 480)), busy=False, emit=messages.append)
            self.assertEqual(session.streak, 0)
            for i in range(3):
                session.update(VisionFrame(1300+i*100, (640, 480), (), face),
                               busy=False, emit=messages.append)
            self.assertEqual(session.phase, 'SELECT')
            self.assertEqual(messages, ['[ROBOT] Thanks for looking at me!'])

    def test_explicit_center_calibration_offsets_head_and_gaze(self):
        with tempfile.TemporaryDirectory() as directory:
            session = JointAttentionSession(Mock(), Path(directory) / 'name.json')
            face = FaceObservation((.5, .5), (0, 0, 1, 1), 18, 10, None, None,
                                   Gaze(looking_at_camera=False, yaw_deg=25, pitch_deg=15))
            session.calibrate_center(VisionFrame(1000, (640, 480), (), face))
            self.assertEqual(session.angles.head(face), (0, 0))
            self.assertEqual(session.angles.gaze(face.gaze), (0, 0))


class GeneratedDialogueTests(unittest.TestCase):
    def test_calls_model_for_question_and_answer_outside_camera_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = Mock()
            session = JointAttentionSession(brain, Path(directory) / 'name.json')
            def respond(prompt, sensor_context=None):
                self.assertFalse(session.lock._is_owned())
                return ('What can you do with a phone?' if 'child_answer' not in sensor_context
                        else 'Yes, phones let us talk to people!')
            brain.respond.side_effect = respond
            session.active = True
            session.enter('SELECT')
            prompts = []
            session.update(VisionFrame(1000, (640, 480), (obj(),)), busy=False, emit=prompts.append)
            brain.respond.assert_not_called()
            self.assertEqual(prompts[0](), 'What can you do with a phone?')
            reply = session.handle('Call my family')
            self.assertEqual(brain.respond.call_count, 1)
            self.assertEqual(reply(), 'Yes, phones let us talk to people! Can you look at the phone?')
            self.assertEqual(brain.respond.call_args.kwargs['sensor_context']['child_answer'], 'Call my family')
            self.assertEqual(session.phase, 'LOOK')

    def test_model_outage_and_invalid_output_use_fallbacks(self):
        from app.errors import ServiceError
        with tempfile.TemporaryDirectory() as directory:
            brain = Mock()
            session = JointAttentionSession(brain, Path(directory) / 'name.json')
            brain.respond.side_effect = ServiceError('offline')
            self.assertEqual(session.ask_about_object('phone'), 'Do you know what a phone is?')
            self.assertEqual(session.answer_reply('phone', 'Question?', 'yes'),
                             'Thanks for telling me! Can you look at the phone?')
            brain.respond.side_effect = None
            brain.respond.return_value = 'First question? Second question?'
            self.assertEqual(session.ask_about_object('book'), 'Do you know what a book is?')


if __name__ == '__main__':
    unittest.main()
