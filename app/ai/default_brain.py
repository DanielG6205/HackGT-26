"""Temporary conversation replies without an AI API key."""


class DefaultBrain:
    def remember_assistant(self, text):
        pass

    def respond(self, user_text, sensor_context=None):
        return "Got it! Tell me more." if user_text.strip() else ""
