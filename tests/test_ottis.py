"""Ottis: spoken looking game + wake-gated Grok conversation, without servo control."""
import argparse
import logging
import time
from dataclasses import replace
from pathlib import Path

from app.ai.groq_client import GroqClient
from app.ai.grok_client import GrokClient
from app.config import Settings
from app.conversation.ottis import CHILD_PROMPT, OttisAudio, OttisDialogue
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService
from app.vision.interaction import GazeInteraction
from app.vision.sensor_provider import VisionSensorProvider

# Keep game requests about familiar objects; never ask a child to handle them.
PLAY_OBJECTS = {'bottle', 'cup', 'bowl', 'book', 'teddy bear', 'sports ball',
                'chair', 'clock', 'potted plant', 'banana', 'apple', 'orange',
                'backpack', 'umbrella', 'cell phone', 'keyboard', 'mouse',
                'remote', 'laptop', 'tv', 'vase', 'handbag', 'hat'}


def main(argv=None, *, test_setup=None):
    if test_setup is None:
        import sys
        from app.main import main as run_app
        return run_app(['--mock-robot', *(sys.argv[1:] if argv is None else argv)])
    parser = argparse.ArgumentParser(description=(
        'Ottis camera/speech game with a correct-answer servo 1 reward and gaze servo 3 reward.'
        if test_setup else __doc__))
    parser.add_argument('--brain', choices=('grok', 'groq'), default='grok',
                        help='grok uses an xAI key; groq is a separate provider')
    parser.add_argument('--input-device', help='Microphone index or name (see python -m sounddevice)')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--yolo-model', default=None)
    parser.add_argument('--memory', default=str(Path(__file__).resolve().parent / '.ottis/name.json'))
    if test_setup:
        test_setup.add_arguments(parser)
    args = parser.parse_args(argv)
    if test_setup:
        test_setup.configure(args, parser)
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    settings = Settings.from_env()
    if args.input_device is not None:
        value = args.input_device
        settings = replace(settings, input_device=int(value) if value.isdecimal() else value)
    import sounddevice as sd
    microphone = sd.query_devices(settings.input_device, 'input')
    print('Microphone:', microphone['name'], flush=True)
    sd.check_input_settings(device=settings.input_device, channels=1, dtype='int16', samplerate=16000)
    settings.require('xai_api_key' if args.brain == 'grok' else 'groq_api_key',
                     'elevenlabs_api_key', 'elevenlabs_voice_id')
    client_type = GrokClient if args.brain == 'grok' else GroqClient
    print('Conversation and questions provider:', args.brain, flush=True)
    brain = client_type(settings, system_prompt=CHILD_PROMPT)
    dialogue = OttisDialogue(brain, args.memory)
    sensors = VisionSensorProvider()
    audio = OttisAudio(SpeechService(settings), ListenerService(settings), dialogue, sensors,
                       question_brain=client_type(settings, system_prompt=CHILD_PROMPT))
    if test_setup:
        test_setup.bind(dialogue, audio)
    import cv2
    from app.vision.camera import Camera
    from app.vision.pipeline import VisionPipeline
    from app.vision.visualizer import draw

    def new_game():
        return GazeInteraction(emit=audio.emit, require_eye_contact=False,
                               hold_frames=3, max_frame_gap=2, timeout=12, delay=12,
                               allow_center_prompt=True)

    game = new_game()
    was_active = False
    phase = "LOOK_BACK"
    phase_started = None
    started = False
    try:
        if test_setup:
            test_setup.open()
        with VisionPipeline(yolo_model=args.yolo_model, image_size=args.imgsz,
                            device=args.device) as vision, Camera(args.camera, args.width, args.height) as camera:
            print('Say "Hi Ottis", then give a first name and confirm it. Say "let’s play" to resume the game.')
            print('Microphone audio is transcribed by ElevenLabs while waiting for Ottis. No audio saved locally.')
            print('Only the confirmed name is saved locally. Say "Ottis forget my name" to delete it. q quits.')
            audio.thread.start()
            started = True
            while True:
                frame, timestamp = camera.read()
                snapshot = vision.process(frame, timestamp)
                sensors.update(snapshot)
                if test_setup:
                    test_setup.tick()
                if audio.error:
                    raise RuntimeError(audio.error)
                active = dialogue.active
                if was_active and not active:
                    game = new_game()
                    phase = "LOOK_BACK"
                    phase_started = None
                was_active = active
                if not active:
                    now = time.monotonic()
                    if phase == 'LOOK_BACK' and not audio.busy.is_set():
                        audio.emit('[ROBOT] Hey, can you look back at me?')
                        phase, phase_started = 'WAIT_BACK', None
                    elif phase == 'WAIT_BACK' and not audio.busy.is_set():
                        if phase_started is None:
                            phase_started = now
                        if (snapshot.face and snapshot.face.gaze.looking_at_camera) or now - phase_started > 5:
                            audio.ask_question()
                            phase, phase_started = 'QUESTION', None
                    elif phase == 'QUESTION' and not audio.busy.is_set():
                        if phase_started is None:
                            phase_started = now
                        if not dialogue.game_question or now - phase_started > 12:
                            dialogue.game_question = False
                            phase = 'OBJECT'
                    elif phase == 'OBJECT':
                        objects = tuple(o for o in snapshot.objects if o.label in PLAY_OBJECTS and o.confidence >= .25)
                        game.update(snapshot.face.gaze if snapshot.face else None,
                                    timestamp / 1000, objects, prompt_pending=audio.paused)
                        if game.state.name == 'COOLDOWN':
                            phase, phase_started = 'REST', now
                    elif phase == 'REST' and not audio.busy.is_set() and now - phase_started > 12:
                        game = new_game()
                        phase = 'LOOK_BACK'
                if audio.paused and dialogue.active:
                    dialogue.game_question = False
                display = draw(frame, snapshot)
                status = 'TALKING' if active else phase
                cv2.putText(display, f'Ottis: {status} | {audio.status} | q: quit',
                            (10, 25), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 2)
                cv2.imshow('Ottis', display)
                if cv2.waitKey(1) & 0xff == ord('q'):
                    break
                if cv2.getWindowProperty('Ottis', cv2.WND_PROP_VISIBLE) < 1:
                    break
    finally:
        if test_setup:
            test_setup.close()
        if started:
            audio.close()
        cv2.destroyAllWindows()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f'[OTTIS ERROR] {exc}')
        raise SystemExit(1)
