"""Full regression suite and manual camera/audio integration launcher.

python tests/tests-full.py                 # offline regression tests
python tests/tests-full.py --live          # camera + free speech, mock robot
python tests/tests-full.py --live --mode game  # guided calibration + looking game
python tests/tests-full.py --check-grok    # real xAI request, no audio/hardware
"""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class FullRegressionTests(unittest.TestCase):
    def test_free_conversation_uses_brain_without_face_or_game(self):
        from app.conversation.joint_attention import JointAttentionSession
        from app.vision.models import VisionFrame
        with tempfile.TemporaryDirectory() as directory:
            brain = Mock()
            brain.respond.return_value = 'Dinosaurs are fun!'
            session = JointAttentionSession(brain, Path(directory) / 'name.json')
            session.active = True
            session.enter('CHAT')
            response = session.handle('Tell me about dinosaurs')
            brain.respond.assert_not_called()
            self.assertEqual(response(), 'Dinosaurs are fun!')
            emit = Mock()
            session.update(VisionFrame(1000, (640, 480)), busy=False, emit=emit)
            session.update(VisionFrame(60000, (640, 480)), busy=False, emit=emit)
            self.assertEqual(session.phase, 'CHAT')
            emit.assert_not_called()
            session.handle('lets play')
            self.assertEqual(session.phase, 'ATTENTION')
            session.handle('just talk')
            self.assertEqual(session.phase, 'CHAT')

    def test_mirrored_calibration_maps_to_raw_camera(self):
        from app.vision.look_calibration import from_mirrored_samples
        from app.vision.models import FaceObservation, Gaze
        points = {'center': (0, 0), 'left': (20, 0), 'right': (-20, 0),
                  'up': (0, -20), 'down': (0, 20)}
        samples = {key: [{'head': point, 'gaze': None}] * 20
                   for key, point in points.items()}
        calibration = from_mirrored_samples(samples)
        face = FaceObservation((.5, .5), (0, 0, 1, 1), 20, 0, None, None, Gaze())
        self.assertAlmostEqual(calibration.points(face)['head'][0], .95)
        self.assertFalse(calibration.centered(face))

    def test_lax_attention_and_missing_face(self):
        from app.vision.angles import AngularGaze
        angles = AngularGaze()
        self.assertEqual(angles.attention_cues(None, (16, 3)), ('head',))
        self.assertEqual(angles.attention_cues(None, None), ())
        self.assertEqual(angles.attention_cues(None, (40, 0)), ())

    def test_landmark_face_turn_without_irises(self):
        import numpy as np
        from app.vision.gaze_tracker import estimate_face_direction
        points = np.full((468, 2), .5)
        points[33], points[263] = (.3, .35), (.7, .35)
        points[61], points[291] = (.4, .7), (.6, .7)
        points[1] = (.6, .54)
        self.assertGreater(estimate_face_direction(points, 640, 480)[0], 15)
        points[1] = (.4, .54)
        self.assertLess(estimate_face_direction(points, 640, 480)[0], -15)
        self.assertIsNone(estimate_face_direction(np.zeros((468, 2)), 640, 480))


def main():
    args = sys.argv[1:]
    if '--check-grok' in args:
        from app.ai.grok_client import GrokClient
        from app.errors import ServiceError
        try:
            brain = GrokClient()
            print('Provider: xAI/Grok | model:', brain.settings.xai_model)
            print('Live response:', brain.respond('Reply only with: Connected'))
            return 0
        except (ServiceError, ValueError) as exc:
            print('[GROK CHECK FAILED]', exc)
            return 1
    if '--live' in args:
        from app.main import main as run_app
        return run_app([arg for arg in args if arg != '--live'] + ['--mock-robot'])
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(FullRegressionTests)
    for pattern in ('test_joint_attention.py', 'test_look_calibration.py',
                    'test_gaze_interaction.py', 'test_eye_diagnostic.py',
                    'test_groq_wiring.py', 'test_ottis.py', 'test_conversation.py'):
        suite.addTests(loader.discover(str(ROOT / 'tests'), pattern=pattern))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
