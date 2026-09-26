"""Manual end-to-end conversation with Groq; say goodbye or press Ctrl+C."""
import logging

from app.ai.groq_client import GroqClient
from app.config import Settings
from app.conversation import ConversationManager
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
        brain = GroqClient(settings)
        conversation = ConversationManager(
            SpeechService(settings),
            ListenerService(settings),
            brain,
        )
        conversation.start()
    except (ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
