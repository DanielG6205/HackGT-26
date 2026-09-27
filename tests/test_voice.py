import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import Settings
from app.errors import ServiceError
from app.ai.grok_client import GrokClient
from app.conversation import ConversationManager, ConversationState
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService
from elevenlabs.realtime import RealtimeEvents

SETTINGS = Settings(elevenlabs_api_key="fake", elevenlabs_voice_id="voice", xai_api_key="fake")


class VoiceTests(unittest.TestCase):
    def test_half_duplex_and_exit(self):
        events = []
        speech = SimpleNamespace(speak=lambda text: events.append(("speak", text)))
        texts = iter(["My name is Daniel", "Goodbye."])
        def listen(**kwargs):
            events.append(("listen", ""))
            return next(texts)
        brain = MagicMock()
        brain.respond.return_value = "Hi Daniel"
        manager = ConversationManager(speech, SimpleNamespace(listen=listen), brain)
        manager.start("Hello")
        self.assertEqual([e[0] for e in events], ["speak", "listen", "speak", "listen", "speak"])
        brain.remember_assistant.assert_called_once_with("Hello")
        brain.respond.assert_called_once_with("My name is Daniel", sensor_context=None)
        self.assertEqual(manager.state, ConversationState.IDLE)

    def test_background_stop_and_duplicate_start(self):
        entered = threading.Event()
        def listen(stop_event):
            entered.set()
            stop_event.wait(2)
            return ""
        manager = ConversationManager(MagicMock(), SimpleNamespace(listen=listen), MagicMock())
        worker = manager.start(greeting="", background=True)
        self.assertTrue(entered.wait(1))
        with self.assertRaises(RuntimeError):
            manager.start()
        manager.stop()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(manager.state, ConversationState.IDLE)

    def test_recoverable_failure_and_empty_transcript(self):
        listener = MagicMock()
        listener.listen.side_effect = [ServiceError("offline"), "", "bye"]
        manager = ConversationManager(MagicMock(), listener, MagicMock())
        with patch.object(manager._stop, "wait", return_value=False):
            manager.start(greeting="")
        self.assertEqual(listener.listen.call_count, 3)
        manager.brain.respond.assert_not_called()

    def test_stream_alignment_drain_callbacks_and_failure(self):
        with patch("app.speech.speech.ElevenLabs") as client, patch("app.speech.speech.sd.RawOutputStream") as output:
            def chunks():
                yield b"a"
                yield b"bcd"
            client.return_value.text_to_speech.stream.return_value = chunks()
            events = []
            service = SpeechService(SETTINGS, lambda: events.append(service.is_speaking),
                                    lambda: events.append(service.is_speaking))
            service.speak("hello")
            speaker = output.return_value.__enter__.return_value
            speaker.write.assert_called_once_with(b"abcd")
            speaker.stop.assert_called_once()
            self.assertEqual(events, [True, False])
            client.return_value.text_to_speech.stream.side_effect = OSError("secret")
            with self.assertRaises(ServiceError) as caught:
                service.speak("again")
            self.assertNotIn("secret", str(caught.exception))
            self.assertFalse(service.is_speaking)

    def test_grok_memory_and_failed_turn_rollback(self):
        with patch("app.ai.grok_client.Client") as client:
            brain = GrokClient(SETTINGS)
            brain.remember_assistant("Hello")
            chat = client.return_value.chat.create.return_value
            chat.sample.return_value.content = "Hi Daniel"
            self.assertEqual(brain.respond("I'm Daniel", {"person_detected": True}), "Hi Daniel")
            self.assertEqual(len(brain.history), 4)
            brain.respond("What's my name?")
            sent = client.return_value.chat.create.call_args.kwargs["messages"]
            self.assertIn("Daniel", str(sent))
            self.assertNotIn("person_detected", str(sent))
            before = list(brain.history)
            chat.sample.side_effect = RuntimeError("secret")
            with self.assertRaises(ServiceError):
                brain.respond("retry me")
            self.assertEqual(brain.history, before)

    def run_listener(self, mode):
        handlers = {}
        connection = MagicMock()
        connection.on.side_effect = lambda name, callback: handlers.__setitem__(name, callback)
        connection.close = AsyncMock()
        async def send(data):
            if mode == "transcript":
                handlers[RealtimeEvents.COMMITTED_TRANSCRIPT]({"text": "hello robot"})
            elif mode == "error":
                handlers[RealtimeEvents.ERROR]({"message_type": "auth_error"})
        connection.send = AsyncMock(side_effect=send)
        settings = Settings(elevenlabs_api_key="fake", listen_timeout=0.03)
        with patch("app.speech.listener.ElevenLabs") as client, patch("app.speech.listener.sd.RawInputStream") as microphone:
            async def connect_after_capture(*args, **kwargs):
                microphone.assert_called_once()
                return connection
            client.return_value.speech_to_text.realtime.connect = AsyncMock(side_effect=connect_after_capture)
            def open_mic(**kwargs):
                kwargs["callback"](b"\0" * 3200, 1600, None, False)
                return MagicMock()
            microphone.side_effect = open_mic
            listener = ListenerService(settings)
            if mode == "error":
                with self.assertRaises(ServiceError):
                    listener.listen()
            else:
                self.assertEqual(listener.listen(), "hello robot" if mode == "transcript" else "")
            connection.close.assert_awaited_once()
            self.assertFalse(listener._lock.locked())

    def test_listener_committed_transcript(self):
        self.run_listener("transcript")

    def test_listener_silence_timeout(self):
        self.run_listener("silence")

    def test_listener_auth_failure_cleanup(self):
        self.run_listener("error")

    def test_microphone_permission_failure_does_not_open_connection(self):
        with patch("app.speech.listener.ElevenLabs") as client, patch(
            "app.speech.listener.sd.RawInputStream", side_effect=PermissionError("private")
        ):
            connection = MagicMock()
            connection.close = AsyncMock()
            client.return_value.speech_to_text.realtime.connect = AsyncMock(return_value=connection)
            listener = ListenerService(SETTINGS)
            with self.assertRaises(ServiceError) as caught:
                listener.listen()
            self.assertNotIn("private", str(caught.exception))
            client.return_value.speech_to_text.realtime.connect.assert_not_awaited()
            self.assertFalse(listener._lock.locked())

    def test_invalid_config(self):
        for value in (0, -1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                Settings(listen_timeout=value)


if __name__ == "__main__":
    unittest.main()
