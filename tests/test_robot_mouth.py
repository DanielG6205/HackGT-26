"""Offline mouth lifecycle and speech-playback integration checks."""
import os
import unittest
from unittest.mock import Mock, patch

from app.robot.mouth import MouthAnimator
from app.config import Settings
from app.speech.speech import SpeechService
from app.errors import ServiceError


class MouthTests(unittest.TestCase):
    def test_disabled_by_default_and_bad_config_is_nonfatal(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(MouthAnimator.from_env())
        with patch.dict(os.environ, {'ROBOT_MOUTH_CONFIG': '/nonexistent/mouth.json'}, clear=True):
            self.assertIsNone(MouthAnimator.from_env())

    def test_shared_servo_config(self):
        from pathlib import Path
        from app.robot.gaze import load_axes
        path = Path(__file__).resolve().parents[1] / 'config/robot-servos.example.json'
        with patch.dict(os.environ, {'ROBOT_MOUTH_CONFIG': str(path),
                                    'ROBOT_MOUTH_PORT': 'test-usb'}, clear=True):
            mouth = MouthAnimator.from_env()
            self.assertIsNotNone(mouth)
            self.assertEqual(mouth.config['pin'], 11)
            self.assertEqual(len(load_axes(path)), 5)

    def test_shared_transport_and_stop(self):
        link = Mock()
        animator = MouthAnimator(dict(pin=11, min_deg=85, closed_deg=90, open_deg=95, max_deg=95), 'usb')
        with patch('app.robot.mouth.SerialTransport.active', return_value=link), patch('app.robot.mouth.wait_for_reply'):
            try:
                animator.start()
                self.assertIn(('TALK,1',), [c.args for c in link.send_line.call_args_list])
                animator.stop()
                self.assertEqual(link.send_line.call_args.args, ('MOUTH_CLOSE',))
                self.assertIsNone(animator.thread)
                animator.close()
                link.close.assert_not_called()
            finally:
                animator.close()

    def test_stop_cannot_be_followed_by_a_late_heartbeat(self):
        animator = MouthAnimator(dict(pin=11, min_deg=60, closed_deg=60, open_deg=110, max_deg=110), 'usb')
        animator.link = Mock()
        # Reproduce stop being requested after heartbeat wait but before send.
        def interrupted_wait(timeout):
            animator.stop_event.set()
            return False
        with patch.object(animator.stop_event, 'wait', side_effect=interrupted_wait):
            animator._heartbeat()
        animator.link.send_line.assert_not_called()
        with patch('app.robot.mouth.wait_for_reply') as reply:
            animator.stop()
            self.assertEqual(animator.link.send_line.call_args.args, ('MOUTH_CLOSE',))
            self.assertEqual(reply.call_args.args[1], 'MOUTH_CLOSED,60')

    def test_prepare_closes_without_talking(self):
        link = Mock()
        animator = MouthAnimator(dict(pin=11, min_deg=60, closed_deg=60, open_deg=110, max_deg=110), 'usb')
        with patch('app.robot.mouth.SerialTransport.active', return_value=link), patch('app.robot.mouth.wait_for_reply'):
            self.assertTrue(animator.prepare())
            commands = [c.args[0] for c in link.send_line.call_args_list]
            self.assertIn('MOUTH_CONFIG,11,60,60,110,110', commands)
            self.assertEqual(commands[-1], 'TALK,0')
            self.assertNotIn('TALK,1', commands)
            self.assertIsNone(animator.thread)
            animator.close()

    def test_playback_start_drain_and_error_cleanup(self):
        settings = Settings(elevenlabs_api_key='fake', elevenlabs_voice_id='fake')
        events = []
        mouth = Mock()
        mouth.start.side_effect = lambda: events.append('mouth start')
        mouth.stop.side_effect = lambda: events.append('mouth stop')
        with patch('app.robot.mouth.MouthAnimator.from_env', return_value=mouth), \
             patch('app.speech.speech.ElevenLabs') as client, \
             patch('app.speech.speech.sd.RawOutputStream') as output:
            speech = SpeechService(settings)
            speaker = output.return_value.__enter__.return_value
            speaker.write.side_effect = lambda data: events.append('audio write')
            speaker.stop.side_effect = lambda: events.append('audio drained')
            def chunks():
                events.append('tts first byte')
                yield b'a'  # Incomplete sample must not start motion.
                self.assertNotIn('mouth start', events)
                yield b'b'
            client.return_value.text_to_speech.stream.return_value = chunks()
            speech.speak('hello')
            self.assertEqual(events, ['tts first byte', 'mouth start', 'audio write', 'audio drained', 'mouth stop'])
            events.clear()
            client.return_value.text_to_speech.stream.side_effect = OSError('offline')
            with self.assertRaises(ServiceError):
                speech.speak('failed')
            self.assertEqual(events, ['mouth stop'])
            client.return_value.text_to_speech.stream.side_effect = None
            client.return_value.text_to_speech.stream.return_value = (c for c in [b'ab'])
            mouth.start.side_effect = OSError('serial failed')
            mouth.stop.side_effect = OSError('serial failed')
            speech.speak('audio still works')
            self.assertFalse(speech.is_speaking)


if __name__ == '__main__':
    unittest.main()
