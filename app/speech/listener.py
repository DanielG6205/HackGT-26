"""One microphone session per utterance; no audio is written to disk."""
import asyncio
import base64
import logging
import queue
import threading

import sounddevice as sd
from elevenlabs.client import ElevenLabs
from elevenlabs.realtime import AudioFormat, CommitStrategy, RealtimeEvents

from app.config import Settings
from app.errors import ServiceError, service_error

log = logging.getLogger(__name__)


class ListenerService:
    def __init__(self, settings=None):
        self.settings = settings or Settings.from_env()
        self.settings.require("elevenlabs_api_key")
        self.client = ElevenLabs(api_key=self.settings.elevenlabs_api_key,
                                 timeout=self.settings.api_timeout)
        self._lock = threading.Lock()

    def listen(self, stop_event=None) -> str:
        """Blocking convenience API. Async callers can await listen_async()."""
        return asyncio.run(self.listen_async(stop_event))

    async def listen_async(self, stop_event=None) -> str:
        if not self._lock.acquire(blocking=False):
            raise ServiceError("Microphone is already listening")
        connection = None
        try:
            if stop_event is not None and stop_event.is_set():
                return ""
            connection = await asyncio.wait_for(
                self.client.speech_to_text.realtime.connect({
                    "model_id": "scribe_v2_realtime",
                    "audio_format": AudioFormat.PCM_16000,
                    "sample_rate": 16000,
                    "commit_strategy": CommitStrategy.VAD,
                    "vad_silence_threshold_secs": self.settings.vad_silence,
                }), timeout=self.settings.api_timeout)
            loop = asyncio.get_running_loop()
            result = loop.create_future()
            first_speech = None
            chunks = queue.Queue(maxsize=20)  # At most two seconds of PCM.
            capture_failed = threading.Event()

            def partial(data):
                nonlocal first_speech
                if data.get("text", "").strip() and first_speech is None:
                    first_speech = loop.time()

            def committed(data):
                text = data.get("text", "").strip()
                if text and not result.done():
                    result.set_result(text)

            def failed(data=None):
                if not result.done():
                    kind = (data or {}).get("message_type", "connection_closed")
                    # Only log known event identifiers, never server payloads.
                    known = {event.value for event in RealtimeEvents}
                    kind = kind if kind in known else "connection_error"
                    result.set_exception(ServiceError(
                        f"ElevenLabs STT: {kind}; check key, credits, terms and network"))

            connection.on(RealtimeEvents.PARTIAL_TRANSCRIPT, partial)
            connection.on(RealtimeEvents.COMMITTED_TRANSCRIPT, committed)
            connection.on(RealtimeEvents.ERROR, failed)
            connection.on(RealtimeEvents.CLOSE, failed)

            def capture(data, frames, timing, status):
                if status:
                    capture_failed.set()
                try:
                    chunks.put_nowait(bytes(data))
                except queue.Full:
                    capture_failed.set()

            with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16",
                                   blocksize=1600, device=self.settings.input_device,
                                   callback=capture):
                log.info("[MIC] Listening...")
                started = loop.time()
                while True:
                    if stop_event is not None and stop_event.is_set():
                        return ""
                    if result.done():
                        return result.result()
                    if capture_failed.is_set():
                        raise ServiceError("Microphone audio overflow; check device or network speed")
                    now = loop.time()
                    if first_speech is None and now - started >= self.settings.listen_timeout:
                        log.info("[MIC] No speech before timeout")
                        return ""
                    if first_speech is not None and now - first_speech >= self.settings.max_utterance:
                        log.info("[MIC] Utterance limit reached; please use a shorter sentence")
                        return ""
                    try:
                        chunk = chunks.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                        continue
                    await asyncio.wait_for(connection.send({
                        "audio_base_64": base64.b64encode(chunk).decode("ascii"),
                    }), timeout=self.settings.api_timeout)
        except ServiceError:
            raise
        except Exception as exc:
            raise service_error("ElevenLabs STT / microphone", exc) from None
        finally:
            # Input stream has already closed before websocket cleanup or return.
            if connection is not None:
                if 'result' in locals():
                    if not result.done():
                        result.cancel()
                    elif not result.cancelled():
                        result.exception()  # Retrieve errors even on cancellation.
                try:
                    await asyncio.wait_for(connection.close(), timeout=3)
                except Exception:
                    log.warning("[MIC] Connection cleanup failed")
            self._lock.release()
