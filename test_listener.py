"""Manual microphone smoke test (uses ElevenLabs credits)."""
import logging
from app.speech.listener import ListenerService

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        print("Speak something:")
        print("Transcript:", ListenerService().listen() or "(no speech before timeout)")
    except (ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
