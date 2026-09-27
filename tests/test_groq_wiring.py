"""Offline tests for Groq brain + vision sensor wiring."""
import unittest
from unittest.mock import MagicMock, patch

from app.ai.groq_client import GroqClient
from app.config import Settings
from app.conversation import ConversationManager
from app.errors import ServiceError
from app.vision.context import slim_sensor_context
from app.vision.models import FaceObservation, Gaze, TrackedObject, VisionFrame
from app.vision.sensor_provider import VisionSensorProvider

SETTINGS = Settings(
    elevenlabs_api_key="fake",
    elevenlabs_voice_id="voice",
    groq_api_key="fake-groq",
)


class GroqWiringTests(unittest.TestCase):
    def test_key_alias(self):
        with patch('app.config.load_dotenv'), patch.dict('os.environ',
                {'GROQ_APIKEY': 'alias-key', 'GROQ_API_KEY': ''}, clear=True):
            self.assertEqual(Settings.from_env().groq_api_key, 'alias-key')

    def test_reset_preserves_child_instructions(self):
        from app.conversation.ottis import CHILD_PROMPT
        with patch('app.ai.groq_client.Groq'):
            brain = GroqClient(SETTINGS, system_prompt=CHILD_PROMPT)
            brain.remember_assistant('Hello')
            brain.reset()
            self.assertEqual(brain.history, [{'role': 'system', 'content': CHILD_PROMPT}])

    def test_groq_respond_and_sensor_not_retained(self):
        with patch("app.ai.groq_client.Groq") as client_cls:
            choice = MagicMock()
            choice.message.content = "Hi there"
            client_cls.return_value.chat.completions.create.return_value.choices = [choice]
            brain = GroqClient(SETTINGS)
            brain.remember_assistant("Hello")
            text = brain.respond("What's up?", {"objects": [{"label": "bottle"}]})
            self.assertEqual(text, "Hi there")
            # History should not keep the ephemeral sensor user message.
            roles = [m["role"] for m in brain.history]
            self.assertEqual(roles, ["system", "assistant", "user", "assistant"])
            sent = client_cls.return_value.chat.completions.create.call_args.kwargs["messages"]
            self.assertTrue(any("bottle" in m.get("content", "") for m in sent))

    def test_groq_failure_safe_error(self):
        with patch("app.ai.groq_client.Groq") as client_cls:
            client_cls.return_value.chat.completions.create.side_effect = RuntimeError("secret-key")
            brain = GroqClient(SETTINGS)
            with self.assertRaises(ServiceError) as caught:
                brain.respond("hello")
            self.assertNotIn("secret-key", str(caught.exception))

    def test_sensor_provider_and_manager(self):
        sensors = VisionSensorProvider()
        frame = VisionFrame(
            timestamp_ms=1,
            image_size=(640, 480),
            objects=(TrackedObject(1, "bottle", 0.9, (0, 0, 1, 1), (100, 100), (0.2, 0.3)),),
            face=FaceObservation(
                face_center=(0.5, 0.4),
                bbox_normalized=(0.4, 0.3, 0.2, 0.3),
                head_yaw=0.0,
                head_pitch=0.0,
                left_iris=None,
                right_iris=None,
                gaze=Gaze(horizontal="CENTER", vertical="CENTER", looking_at_camera=True),
            ),
        )
        sensors.update(frame)
        slim = sensors()
        self.assertEqual(slim["objects"][0]["label"], "bottle")
        self.assertNotIn("landmarks", slim.get("face", {}))
        self.assertEqual(slim_sensor_context(None), None)

        events = []
        speech = MagicMock()
        speech.speak.side_effect = lambda text: events.append(("speak", text))
        listener = MagicMock()
        listener.listen.side_effect = ["hi", "goodbye"]
        brain = MagicMock()
        brain.respond.return_value = "hello back"
        manager = ConversationManager(speech, listener, brain, sensor_provider=sensors)
        manager.start(greeting="")
        brain.respond.assert_called_with("hi", sensor_context=slim)


if __name__ == "__main__":
    unittest.main()
