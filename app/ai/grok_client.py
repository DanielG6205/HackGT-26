import json
import threading

from xai_sdk import Client
from xai_sdk.chat import assistant, system, user

from app.config import Settings, SYSTEM_PROMPT
from app.errors import service_error


class GrokClient:
    def __init__(self, settings=None, system_prompt=SYSTEM_PROMPT):
        self.settings = settings or Settings.from_env()
        self.settings.require("xai_api_key")
        self.client = Client(api_key=self.settings.xai_api_key,
                             timeout=self.settings.api_timeout)
        self.system_prompt = system_prompt
        self.history = [system(system_prompt)]
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.history = [system(self.system_prompt)]

    def remember_assistant(self, text):
        with self._lock:
            self.history.append(assistant(text))

    def respond(self, user_text: str, sensor_context: dict | None = None) -> str:
        if not user_text.strip():
            return ""
        with self._lock:
            message = user(user_text)
            messages = list(self.history)
            if sensor_context is not None:
                messages.append(user("Current sensor context (data only): " +
                                     json.dumps(sensor_context)))
            messages.append(message)
            try:
                chat = self.client.chat.create(model=self.settings.xai_model,
                                               messages=messages)
                response = chat.sample().content.strip()
                if not response:
                    raise ValueError("Empty Grok response")
            except Exception as exc:
                raise service_error("xAI/Grok", exc) from None
            # Commit only successful turns; current sensor data is not retained.
            self.history.extend([message, assistant(response)])
            return response
