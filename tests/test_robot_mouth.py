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

    def test_shared_transport_and_stop(self):
        link = Mock()
        animator = MouthAnimator(dict(pin=11, min_deg=85, closed_deg=90, open_deg=95, max_deg=95), 'usb')
        with patch('app.robot.mouth.SerialTransport.active', return_value=link), patch('app.robot.mouth.wait_for_reply'):
            try:
                animator.start()
                self.assertIn(('TALK,1',), [c.args for c in link.send_line.call_args_list])
                animator.stop()
                self.assertEqual(link.send_line.call_args.args, ('TALK,0',))
                self.assertIsNone(animator.thread)
                animator.close()
                link.close.assert_not_called()
            finally:
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
