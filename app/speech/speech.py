"""Streaming PCM playback; speak() returns only after the speaker drains."""
import logging
import threading
from contextlib import closing

import sounddevice as sd
from elevenlabs.client import ElevenLabs

from app.config import Settings
from app.errors import service_error

log = logging.getLogger(__name__)


class SpeechService:
    def __init__(self, settings=None, on_speech_start=None, on_speech_end=None):
        self.settings = settings or Settings.from_env()
        self.settings.require("elevenlabs_api_key", "elevenlabs_voice_id")
        self.client = ElevenLabs(api_key=self.settings.elevenlabs_api_key,
                                 timeout=self.settings.api_timeout)
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self._lock = threading.Lock()
        self._speaking = threading.Event()

    @property
    def is_speaking(self):
        return self._speaking.is_set()

    @staticmethod
    def _notify(callback):
        if callback:
            try:
                callback()
            except Exception:
                log.warning("[SPEECH] Speech callback failed")

    def speak(self, text):
        if not text.strip():
            return
        with self._lock:
            self._speaking.set()
            try:
                chunks = self.client.text_to_speech.stream(
                    voice_id=self.settings.elevenlabs_voice_id,
                    model_id=self.settings.tts_model, text=text,
                    output_format="pcm_24000",
                    request_options={"max_retries": 0},
                )
                with closing(chunks), sd.RawOutputStream(
                    samplerate=24000, channels=1, dtype="int16",
                    device=self.settings.output_device,
                ) as speaker:
                    pending = b""
                    started = False
                    for chunk in chunks:
                        pending += chunk
                        size = len(pending) // 2 * 2
                        if size:
                            if not started:
                                self._notify(self.on_speech_start)
                                started = True
                            speaker.write(pending[:size])
                            pending = pending[size:]
                    if pending or not started:
                        raise ValueError("Empty or incomplete PCM audio")
                    # PortAudio stop waits for all queued samples to play.
                    speaker.stop()
            except Exception as exc:
                raise service_error("ElevenLabs TTS / speaker", exc) from None
            finally:
                self._speaking.clear()
                self._notify(self.on_speech_end)
