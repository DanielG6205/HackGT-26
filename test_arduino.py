"""Manual Arduino link test (LED blinks; no servos required).

Flash firmware/robot_controller/robot_controller.ino with LED_TEST_MODE 1
(default). Then run:

  python test_arduino.py --mock          # host-only, no board
  python test_arduino.py --port /dev/cu.usbmodem21101

Blink legend (onboard LED when connected):
  CENTER = 1 blink
  LEFT   = 2 blinks
  RIGHT  = 3 blinks
  UP     = 4 blinks
  DOWN   = 5 blinks
  LOOK   = 1 long blink
  EXPR   = 2 short blinks
  SET    = 1 short blink
  PING   = 1 very short blink + PONG on serial
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.robot import MockTransport, RobotController, RobotHardwareConfig
from app.robot.protocol import format_wire

# ---------------------------------------------------------------------------
# Previous simple LED on/off smoke test (kept for reference; not used).
# Uncomment and run only against a sketch that accepts raw "1"/"0" bytes.
# ---------------------------------------------------------------------------
# import serial
# import time
#
# PORT = "/dev/cu.usbmodem21101"  # change this to your Arduino port
#
# arduino = serial.Serial(PORT, 115200)
# time.sleep(2)
#
# print("Blinking Arduino LED...")
#
# for _ in range(5):
#     arduino.write(b"1")
#     time.sleep(0.5)
#
#     arduino.write(b"0")
#     time.sleep(0.5)
#
# arduino.close()
#
# print("Done!")
# ---------------------------------------------------------------------------

# Expected LED blink counts when LED_TEST_MODE firmware is running.
BLINK_LEGEND = {
    "CENTER": 1,
    "LEFT": 2,
    "RIGHT": 3,
    "UP": 4,
    "DOWN": 5,
    "LOOK": 1,   # long blink
    "EXPR": 2,   # short blinks
    "SET": 1,
    "PING": 1,
}


def log(msg: str) -> None:
    print(msg, flush=True)


def read_lines(ser, timeout_s: float = 1.5) -> list[str]:
    """Read Serial lines for up to timeout_s (keeps going while data arrives)."""
    deadline = time.time() + timeout_s
    lines: list[str] = []
    last_data = time.time()
    # Temporarily use a short per-read timeout.
    old_timeout = ser.timeout
    ser.timeout = 0.05
    try:
        while time.time() < deadline:
            raw = ser.readline()
            if raw:
                text = raw.decode("ascii", errors="replace").strip()
                if text:
                    lines.append(text)
                    last_data = time.time()
            elif lines and time.time() - last_data > 0.3:
                break
            else:
                time.sleep(0.01)
    finally:
        ser.timeout = old_timeout
    return lines


def ready_countdown(seconds: float, blinks: int, label: str) -> None:
    """Countdown *before* sending so you are looking at the LED when it blinks."""
    log("")
    log(f">>> NEXT UP: {label}")
    log(f"    Look at the Arduino LED — it should blink {blinks} time(s)")
    total = max(1, int(round(seconds)))
    for remaining in range(total, 0, -1):
        log(f"    get ready... {remaining}")
        time.sleep(1.0)
    log("    >>> SENDING NOW — count the blinks!")


def blink_wait(blinks: int) -> None:
    """Stay quiet while the board finishes blinking (matches slower firmware timing)."""
    # Firmware: ~250ms on + 200ms off per blink (last blink has no trailing off).
    on_ms, off_ms = 250, 200
    long_ms = 600  # LOOK uses one long blink
    if blinks <= 0:
        time.sleep(0.4)
        return
    if blinks == 1:
        duration = (long_ms + 150) / 1000.0
    else:
        duration = (blinks * on_ms + (blinks - 1) * off_ms + 200) / 1000.0
    time.sleep(duration)
    log("    (blinks should be finished)")


def wait_for_ready(ser, timeout_s: float = 5.0) -> list[str]:
    log("[host] waiting for Arduino READY / MODE,LED_TEST ...")
    lines = read_lines(ser, timeout_s=timeout_s)
    for line in lines:
        log(f"[arduino] {line}")
    if any(line == "READY" for line in lines):
        log("[host] board is READY")
    else:
        log("[host] WARN: did not see READY — re-flash robot_controller.ino,")
        log("       close Arduino Serial Monitor, then retry.")
    if any("MODE,LED_TEST" in line for line in lines):
        log("[host] LED_TEST_MODE confirmed")
    else:
        log("[host] WARN: did not see MODE,LED_TEST — ACK blinks need LED_TEST_MODE 1")
    return lines


def run_mock_tests() -> int:
    """Verify host protocol encoding without a board."""
    log("=" * 60)
    log("MOCK TESTS (no Arduino) — checking what we would send on the wire")
    log("=" * 60)
    transport = MockTransport()
    robot = RobotController(
        transport,
        RobotHardwareConfig(deadzone=0.0, max_look_speed=100.0),
    )

    cases = [
        ("PING", lambda: robot.ping(), "PING", BLINK_LEGEND["PING"]),
        ("CENTER", lambda: robot.center_eyes(), "CENTER", BLINK_LEGEND["CENTER"]),
        ("LEFT", lambda: robot.nudge("LEFT"), "MOVE,LEFT", BLINK_LEGEND["LEFT"]),
        ("RIGHT", lambda: robot.nudge("RIGHT"), "MOVE,RIGHT", BLINK_LEGEND["RIGHT"]),
        ("UP", lambda: robot.nudge("UP"), "MOVE,UP", BLINK_LEGEND["UP"]),
        ("DOWN", lambda: robot.nudge("DOWN"), "MOVE,DOWN", BLINK_LEGEND["DOWN"]),
        ("LOOK", lambda: robot.snap_look(0.72, 0.41), "LOOK,0.7200,0.4100", BLINK_LEGEND["LOOK"]),
        ("EXPR", lambda: robot.set_expression("happy"), "EXPR,happy", BLINK_LEGEND["EXPR"]),
        ("SET", lambda: robot.set_servo("eye_x", 95.0), "SET,eye_x,95.00", BLINK_LEGEND["SET"]),
    ]

    failed = 0
    for name, action, expect_substr, blinks in cases:
        transport.clear()
        action()
        sent = list(transport.lines)
        ok = any(expect_substr in line for line in sent)
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        log(
            f"[{status}] {name:7s}  wire={sent}  "
            f"expect contains {expect_substr!r}  "
            f"→ LED should blink {blinks}x on real board"
        )
        log(f"         raw bytes: {[format_wire(s) for s in sent]}")

    robot.close()
    log("-" * 60)
    if failed:
        log(f"MOCK RESULT: {failed} failed")
        return 1
    log("MOCK RESULT: all host encodings OK")
    return 0


def run_serial_tests(port: str, baud: int, watch_seconds: float = 3.0) -> int:
    """Send real protocol commands and print ACK / blink expectations."""
    try:
        import serial
    except ImportError:
        log("[ERROR] pyserial missing; pip install pyserial")
        return 1

    log("=" * 60)
    log(f"SERIAL TESTS on {port} @ {baud}")
    log("Watch the onboard LED. Firmware must be LED_TEST_MODE 1.")
    log(f"Each test: {watch_seconds:.0f}s get-ready countdown → send → blink → next")
    log("=" * 60)

    try:
        ser = serial.Serial(
            port,
            baudrate=baud,
            timeout=0.2,
            write_timeout=2.0,
            dsrdtr=False,
            rtscts=False,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"[ERROR] could not open {port}: {exc}")
        log("Tip: unplug/replug, close Serial Monitor, or pass --port")
        return 1

    try:
        # Opening the port usually resets the Arduino; give it time to print READY.
        # Boot also does 3 quick blinks — wait those out before tests.
        time.sleep(2.5)
        boot = wait_for_ready(ser)
        if not boot:
            log("[host] no boot lines yet; waiting 2s more and sending PING...")
            time.sleep(2.0)
            ser.write(format_wire("PING"))
            ser.flush()
            for line in read_lines(ser, timeout_s=2.0):
                log(f"[arduino] {line}")
        log("[host] waiting 2s so boot blinks are fully done...")
        time.sleep(2.0)

        def send(line: str) -> None:
            try:
                ser.reset_input_buffer()
            except Exception:  # noqa: BLE001
                pass
            payload = format_wire(line)
            log(f"[host] SEND  {line!r}  bytes={payload!r}")
            ser.write(payload)
            ser.flush()

        steps = [
            ("PING", "PING", BLINK_LEGEND["PING"], "PONG"),
            ("CENTER eyes", "CENTER", BLINK_LEGEND["CENTER"], "ACK,CENTER"),
            ("turn LEFT", "MOVE,LEFT", BLINK_LEGEND["LEFT"], "ACK,MOVE,LEFT"),
            ("turn RIGHT", "MOVE,RIGHT", BLINK_LEGEND["RIGHT"], "ACK,MOVE,RIGHT"),
            ("look UP", "MOVE,UP", BLINK_LEGEND["UP"], "ACK,MOVE,UP"),
            ("look DOWN", "MOVE,DOWN", BLINK_LEGEND["DOWN"], "ACK,MOVE,DOWN"),
            ("LOOK target", "LOOK,0.7200,0.4100", BLINK_LEGEND["LOOK"], "ACK,LOOK"),
            ("expression", "EXPR,happy", BLINK_LEGEND["EXPR"], "ACK,EXPR"),
            ("set eye_x", "SET,eye_x,95.00", BLINK_LEGEND["SET"], "ACK,SET"),
        ]

        failed = 0
        for label, command, blinks, expect in steps:
            log("")
            log("=" * 60)
            log(f">>> TEST: {label}")
            log(f"    Wire command: {command}")
            log(f"    Expect serial: contains {expect!r}")
            log(f"    Expect LED:    exactly {blinks} blink(s) for THIS test only")

            # Countdown first so you are already watching when blinks start.
            ready_countdown(watch_seconds, blinks, label)
            send(command)

            reply = read_lines(ser, timeout_s=2.0)
            if not reply:
                log("[host] no reply yet — waiting a bit longer...")
                reply = read_lines(ser, timeout_s=2.0)
            for line in reply:
                log(f"[arduino] {line}")
            if any(expect in line for line in reply):
                log(f"[PASS] serial reply OK for {label}")
            else:
                failed += 1
                log(f"[FAIL] missing {expect!r} in replies {reply}")
                if not reply:
                    log("       Empty replies usually mean:")
                    log("       1) Flash firmware/robot_controller/robot_controller.ino")
                    log("          (LED_TEST_MODE must be 1)")
                    log("       2) Close Arduino IDE Serial Monitor (it locks the port)")
                    log("       3) Confirm --port matches the board")

            # Keep this test's blinks from overlapping the next countdown.
            blink_wait(blinks)
            time.sleep(0.5)

        log("-" * 60)
        if failed:
            log(f"SERIAL RESULT: {failed} failed — re-flash LED_TEST_MODE firmware / check port")
            return 1
        log("SERIAL RESULT: all commands got ACK/PONG")
        return 0
    finally:
        ser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--mock", action="store_true", help="host-only wire encoding tests")
    parser.add_argument("--port", default="", help="serial device, e.g. /dev/cu.usbmodem21101")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--watch",
        type=float,
        default=3.0,
        help="seconds of get-ready countdown BEFORE each blink (default 3)",
    )
    args = parser.parse_args(argv)

    log("Blink legend:")
    for name, n in BLINK_LEGEND.items():
        log(f"  {name:7s} → {n} blink(s)")
    log("")

    if args.mock or not args.port:
        code = run_mock_tests()
        if not args.port:
            log("")
            log("No --port given; skipped live serial. Example:")
            log("  python test_arduino.py --port /dev/cu.usbmodem21101")
            return code
        if code != 0:
            return code

    return run_serial_tests(args.port, args.baud, watch_seconds=args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
