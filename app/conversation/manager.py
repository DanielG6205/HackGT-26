"""Sequential audio ownership, optionally hosted in one background thread."""
import logging
import re
import threading
from enum import Enum

from app.errors import ServiceError

log = logging.getLogger(__name__)


class ConversationState(Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    LISTENING = "listening"
    THINKING = "thinking"


class ConversationManager:
    def __init__(self, speech, listener, brain, sensor_provider=None):
        self.speech, self.listener, self.brain = speech, listener, brain
        # Optional callable returning dict | None for the current vision/sensors.
        self.sensor_provider = sensor_provider
        self.state = ConversationState.IDLE
        self._stop = threading.Event()
        self._running = threading.Lock()
        self._thread = None

    def _sensor_context(self):
        if self.sensor_provider is None:
            return None
        try:
            return self.sensor_provider()
        except Exception as exc:  # noqa: BLE001 — never break talk on sensor glitches
            log.error("[ERROR] sensor_provider failed: %s", type(exc).__name__)
            return None

    def _state(self, state):
        self.state = state
        log.info("[STATE] %s", state.name)

    def _speak(self, text):
        self._state(ConversationState.SPEAKING)
        log.info("[ROBOT] %s", text)
        self.speech.speak(text)

    def stop(self):
        """Cooperative stop: current TTS/API call finishes or times out first."""
        self._stop.set()

    def start(self, greeting="Hi Ottis! How are you?", *, background=False):
        if not self._running.acquire(blocking=False):
            raise RuntimeError("Conversation is already running")
        self._stop.clear()
        if background:
            self._thread = threading.Thread(target=self._run, args=(greeting,),
                                            name="robot-conversation", daemon=True)
            try:
                self._thread.start()
            except Exception:
                self._running.release()
                raise
            return self._thread
        self._run(greeting)

    def _run(self, greeting):
        try:
            if greeting:
                try:
                    self._speak(greeting)
                    self.brain.remember_assistant(greeting)
                except ServiceError as exc:
                    log.error("[ERROR] %s", exc)
            while not self._stop.is_set():
                try:
                    self._state(ConversationState.LISTENING)
                    text = self.listener.listen(stop_event=self._stop).strip()
                    if self._stop.is_set():
                        break
                    if not text:
                        self._state(ConversationState.IDLE)
                        self._stop.wait(0.5)
                        continue
                    log.info("[USER] %s", text)
                    normalized = " ".join(re.findall(r"\w+", text.casefold()))
                    if normalized in {"goodbye", "bye", "stop talking"}:
                        try:
                            self._speak("Bye! It was nice talking to you.")
                        finally:
                            self._stop.set()
                        break
                    self._state(ConversationState.THINKING)
                    log.info("[BRAIN] Preparing reply...")
                    response = self.brain.respond(text, sensor_context=self._sensor_context())
                    if not self._stop.is_set():
                        self._speak(response)
                except ServiceError as exc:
                    log.error("[ERROR] %s", exc)
                    self._state(ConversationState.IDLE)
                    self._stop.wait(2)  # Avoid a tight retry loop on outages.
        except KeyboardInterrupt:
            self.stop()
        finally:
            self._state(ConversationState.IDLE)
            self._running.release()
