"""Groq chat brain (OpenAI-compatible completions API)."""
from __future__ import annotations

import json
import threading

from groq import Groq

from app.config import SYSTEM_PROMPT, Settings
from app.errors import service_error


class GroqClient:
    """Same respond/remember_assistant surface as GrokClient."""

    def __init__(self, settings=None, system_prompt=SYSTEM_PROMPT):
        self.settings = settings or Settings.from_env()
        self.settings.require("groq_api_key")
        self.client = Groq(
            api_key=self.settings.groq_api_key,
            timeout=self.settings.api_timeout,
        )
        self.system_prompt = system_prompt
        self.history: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.history = [{"role": "system", "content": self.system_prompt}]

    def remember_assistant(self, text: str) -> None:
        if not text.strip():
            return
        with self._lock:
            self.history.append({"role": "assistant", "content": text})

    def respond(self, user_text: str, sensor_context: dict | None = None) -> str:
        if not user_text.strip():
            return ""
        with self._lock:
            messages = list(self.history)
            if sensor_context is not None:
                messages.append({
                    "role": "user",
                    "content": "Current sensor context (data only): "
                               + json.dumps(sensor_context),
                })
            user_message = {"role": "user", "content": user_text}
            messages.append(user_message)
            try:
                completion = self.client.chat.completions.create(
                    model=self.settings.groq_model,
                    messages=messages,
                )
                response = (completion.choices[0].message.content or "").strip()
                if not response:
                    raise ValueError("Empty Groq response")
            except Exception as exc:
                raise service_error("Groq", exc) from None
            # Commit only successful turns; sensor context is not retained.
            self.history.extend([user_message, {"role": "assistant", "content": response}])
            return response
