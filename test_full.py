"""Full stack demo: camera vision + robot look + Groq conversation + speech.

Runs conversation on a background thread while the main thread owns the camera.
Robot eyes follow the user face (or best non-person object). Groq receives a
slim vision snapshot with each user turn.

  python test_full.py --mock-robot
  python test_full.py --transport bluetooth
  python test_full.py --bluetooth-name PicoRobot
  python test_full.py --port /dev/cu.usbmodem21101   # USB fallback
  python test_full.py --no-vision
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from app.ai.groq_client import GroqClient
from app.config import Settings
from app.conversation import ConversationManager
from app.robot import connect_robot
from app.speech.listener import ListenerService
from app.speech.speech import SpeechService
from app.vision.sensor_provider import VisionSensorProvider


log = logging.getLogger(__name__)


def build_robot(args, settings: Settings):
    return connect_robot(
        mock=args.mock_robot,
        transport=args.transport or None,
        bluetooth_name=args.bluetooth_name or None,
        bluetooth_address=args.bluetooth_address or None,
        wifi_host=args.wifi_host or settings.robot_wifi_host or None,
        wifi_port=args.wifi_port or settings.robot_wifi_port or None,
        serial_port=args.port or settings.robot_serial_port or None,
    )


def drive_robot(robot: RobotController, snapshot) -> None:
    """Look at face if present, else highest-confidence non-person object."""
    if snapshot is None:
        return
    face = snapshot.face
    if face is not None:
        robot.update_from_vision(snapshot)
        robot.look_at_user(face)
        return
    candidates = [o for o in snapshot.objects if o.label != "person"]
    if candidates:
        best = max(candidates, key=lambda o: o.confidence)
        robot.look_at_object(best)
        return
    robot.flush()


def run_vision_loop(args, robot: RobotController, sensors: VisionSensorProvider) -> None:
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
    ) as vision, Camera(args.camera) as camera:
        log.info("[vision] camera ready — press q to quit")
        while True:
            frame, timestamp_ms = camera.read()
            snapshot = vision.process(frame, timestamp_ms)
            sensors.update(snapshot)
            drive_robot(robot, snapshot)
            frame = draw(frame, snapshot)
            state = robot.state
            cv2.putText(
                frame,
                f"look=({state.x:.2f},{state.y:.2f}) eye=({state.eye_x_deg:.0f},{state.eye_y_deg:.0f})",
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (255, 255, 255),
                1,
            )
            cv2.imshow("Robot full stack", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
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
    parser.add_argument("--no-vision", action="store_true", help="conversation only (no camera)")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--yolo-model", default=None)
    parser.add_argument("--face-model", default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--imgsz", type=int, default=416)
    parser.add_argument("--smoothing", type=int, default=5)
    parser.add_argument("--greeting", default="Hi! I'm awake — talk to me while I look around.")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    settings = Settings.from_env()
    settings.require("elevenlabs_api_key", "elevenlabs_voice_id", "groq_api_key")

    sensors = VisionSensorProvider()
    robot = build_robot(args, settings)
    log.info("[robot] transport=%s", type(robot.transport).__name__)
    speech = SpeechService(settings)
    listener = ListenerService(settings)
    brain = GroqClient(settings)
    conversation = ConversationManager(speech, listener, brain, sensor_provider=sensors)

    worker = None
    try:
        robot.center_eyes()
        worker = conversation.start(greeting=args.greeting, background=True)
        if args.no_vision:
            log.info("[main] vision disabled — say goodbye or Ctrl+C to stop")
            while worker.is_alive():
                time.sleep(0.25)
        else:
            run_vision_loop(args, robot, sensors)
    except KeyboardInterrupt:
        pass
    finally:
        conversation.stop()
        if worker is not None:
            worker.join(timeout=30)
        try:
            robot.center_eyes()
        except Exception:  # noqa: BLE001
            pass
        robot.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
