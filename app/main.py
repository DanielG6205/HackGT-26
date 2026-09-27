"""Ottis wake-triggered object conversation and shared-attention game."""
from __future__ import annotations

import argparse
import logging
import sys
import time

from app.config import Settings
from pathlib import Path
from app.conversation.ottis import OttisAudio, CHILD_PROMPT
from app.conversation.joint_attention import JointAttentionSession
from app.robot.look_mapping import LookMapping
from app.vision.angles import AngularGaze
from app.robot import connect_robot
from app.robot.config import RobotHardwareConfig
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService
from app.vision.sensor_provider import VisionSensorProvider


log = logging.getLogger(__name__)


def build_robot(args, settings: Settings):
    config = RobotHardwareConfig.from_env()
    if args.baud:
        config = config.with_updates(serial_baud=args.baud)
    return connect_robot(
        config,
        mock=args.mock_robot,
        transport=args.transport or None,
        bluetooth_name=args.bluetooth_name or None,
        bluetooth_address=args.bluetooth_address or None,
        wifi_host=args.wifi_host or settings.robot_wifi_host or None,
        wifi_port=args.wifi_port or settings.robot_wifi_port or None,
        serial_port=args.port or settings.robot_serial_port or None,
    )


def run_vision_loop(args, robot, sensors, session, audio, mapping) -> None:
    import cv2
    from app.vision.camera import Camera
    from app.vision.pipeline import VisionPipeline
    from app.vision.visualizer import draw

    log.info("[vision] loading models (first run may download weights)...")
    with VisionPipeline(
        yolo_model=args.yolo_model,
        face_model=args.face_model,
        smoothing=args.smoothing,
        device=args.device,
        image_size=args.imgsz,
    ) as vision, Camera(args.camera, args.width, args.height) as camera:
        from app.vision.look_calibration import run_calibration
        if args.mode == 'game' and not args.skip_gaze_calibration:
            session.pixel_calibration = run_calibration(vision, camera)
            if session.pixel_calibration is None:
                return
        audio.thread.start()
        log.info("[vision] camera ready — c: calibrate while looking at camera; q: quit")
        while True:
            frame, timestamp_ms = camera.read()
            snapshot = vision.process(frame, timestamp_ms,
                                      detect_objects=session.phase in {'CHAT', 'SELECT', 'ANSWER', 'LOOK'})
            sensors.update(snapshot)
            if audio.error:
                raise RuntimeError(audio.error)
            with session.lock:
                session.update(snapshot, busy=audio.busy.is_set(), emit=audio.emit,
                               robot=robot, mapping=mapping)
            frame = draw(frame, snapshot)
            state = robot.state
            cv2.putText(
                frame,
                f"{session.phase} | {audio.status} | look=({state.x:.2f},{state.y:.2f})",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
            )
            cv2.imshow("Robot full stack", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("c"):
                if session.pixel_calibration:
                    log.info('[CALIBRATION] Restart the application to redo all five calibration points.')
                else:
                    session.calibrate_center(snapshot)
            if key == ord("q"):
                break
            if cv2.getWindowProperty("Robot full stack", cv2.WND_PROP_VISIBLE) < 1:
                break
    cv2.destroyAllWindows()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock-robot", action="store_true", help="do not connect to robot hardware")
    parser.add_argument("--transport", choices=("auto", "bluetooth", "wifi", "serial", "mock"), default="")
    parser.add_argument("--bluetooth-name", default="", help="BLE name (default PicoRobot)")
    parser.add_argument("--bluetooth-address", default="", help="BLE address or macOS device UUID")
    parser.add_argument("--wifi-host", default="", help="ESP32 IP, e.g. 192.168.4.1")
    parser.add_argument("--wifi-port", type=int, default=0, help="TCP port (default 9000)")
    parser.add_argument("--port", default="", help="USB serial device (fallback)")
    parser.add_argument("--baud", type=int, default=0)
    parser.add_argument("--mode", choices=("chat", "game"), default="chat",
                        help="Free conversation by default; game enables guided looking trials")
    parser.add_argument("--no-vision", action="store_true", help="conversation only (no camera)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280, help="Requested camera capture width")
    parser.add_argument("--height", type=int, default=720, help="Requested camera capture height")
    parser.add_argument("--yolo-model", default=None)
    parser.add_argument("--face-model", default=None)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--smoothing", type=int, default=5)
    parser.add_argument('--brain', choices=('grok', 'groq'), default='grok',
                        help='AI provider: xAI/Grok by default; Groq is a separate optional provider')
    parser.add_argument('--input-device', default=None)
    parser.add_argument('--memory', default=str(Path(__file__).resolve().parents[1] / '.ottis/name.json'))
    parser.add_argument('--eye-calibration', help='JSON camera-to-eye gains and offsets')
    parser.add_argument('--camera-hfov', type=float, default=60, help='Approximate horizontal camera field of view in degrees')
    parser.add_argument('--gaze-tolerance', type=float, default=16, help='Allowed angular error in degrees')
    parser.add_argument('--gaze-yaw-offset', type=float, default=0, help='Observed neutral gaze yaw, subtracted in degrees')
    parser.add_argument('--gaze-pitch-offset', type=float, default=0, help='Observed neutral gaze pitch, subtracted in degrees')
    parser.add_argument('--vad-silence', type=float, default=.6, help='Seconds of silence before submitting speech (default 0.6)')
    parser.add_argument('--skip-gaze-calibration', action='store_true', help='Use the older angular matcher without guided calibration')
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    from dataclasses import replace
    settings = replace(Settings.from_env(), vad_silence=args.vad_silence)
    if args.input_device is not None:
        from dataclasses import replace
        value = args.input_device
        settings = replace(settings, input_device=int(value) if value.isdecimal() else value)
    settings.require("elevenlabs_api_key", "elevenlabs_voice_id",
                     "groq_api_key" if args.brain == 'groq' else 'xai_api_key')
    mapping = LookMapping.load(args.eye_calibration)

    sensors = VisionSensorProvider()
    if args.brain == 'grok':
        from app.ai.grok_client import GrokClient
        brain = GrokClient(settings, system_prompt=CHILD_PROMPT)
    else:
        from app.ai.groq_client import GroqClient
        brain = GroqClient(settings, system_prompt=CHILD_PROMPT)
    session = JointAttentionSession(brain, args.memory, angles=AngularGaze(
        horizontal_fov=args.camera_hfov, tolerance=args.gaze_tolerance,
        yaw_offset=args.gaze_yaw_offset, pitch_offset=args.gaze_pitch_offset))
    if args.mode == 'chat' or args.no_vision:
        session.active = True
        session.enter('CHAT')
    audio = OttisAudio(SpeechService(settings), ListenerService(settings), session, sensors)
    robot = build_robot(args, settings)
    if args.mock_robot or args.transport == 'mock':
        log.info('[robot] Mock movement only; camera, microphone and speech remain live.')
    try:
        robot.center_eyes()
        log.info('[AI] Provider=%s model=%s', args.brain, settings.xai_model if args.brain == 'grok' else settings.groq_model)
        log.info('Talk freely in chat mode. Say lets play for a looking game, or just talk to return to chat.')
        if args.no_vision:
            audio.thread.start()
            log.info('Camera disabled: free conversation is ready; object trials need the camera.')
            while audio.thread.is_alive():
                time.sleep(0.25)
            if audio.error:
                raise RuntimeError(audio.error)
        else:
            run_vision_loop(args, robot, sensors, session, audio, mapping)
    except KeyboardInterrupt:
        pass
    finally:
        if audio.thread.ident is not None:
            audio.close()
        try:
            robot.center_eyes()
        finally:
            robot.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
