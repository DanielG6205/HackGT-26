"""Manual end-to-end conversation; say goodbye or press Ctrl+C."""
import logging
# from app.ai.grok_client import GrokClient  # Restore when you have an xAI key.
from app.ai.default_brain import DefaultBrain
from app.config import Settings
from app.conversation import ConversationManager
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Avoid SDK request logs; application errors omit sensitive payloads.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
        brain = DefaultBrain()
        # brain = GrokClient(settings)  # Enable with the import above later.
        conversation = ConversationManager(SpeechService(settings),
                                           ListenerService(settings), brain)
        conversation.start()
    except (ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
