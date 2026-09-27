"""Manual speaker smoke test (uses ElevenLabs credits)."""
from app.speech.speech import SpeechService

if __name__ == "__main__":
    try:
        SpeechService().speak("Hi Ottis! Nice to meet you.")
    except (ValueError, RuntimeError) as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
    except KeyboardInterrupt:
        pass
