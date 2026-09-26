"""Interactive calibration / test mode for robot eye (and head) servos."""
from __future__ import annotations

import argparse
import sys

from .config import RobotHardwareConfig, ServoAxisConfig
from .controller import RobotController
from .mapping import norm_to_angle
from .transport.mock import MockTransport
from .transport.serial_transport import SerialTransport


HELP = """\
Commands:
  left / right / up / down / center   nudge look target (also sends MOVE,*)
  look X Y                            look_at normalized coords (0-1)
  expr NAME                           set_expression
  set AXIS ANGLE                      direct SET,axis,angle (eye_x|eye_y|head_x|head_y)
  sweep AXIS                          sweep an axis across min→max→center
  ping                                send PING
  state                               print current mapped angles
  help                                show this help
  quit                                exit
"""


def _print_state(robot: RobotController) -> None:
    s = robot.state
    print(
        f"look=({s.x:.3f},{s.y:.3f})  "
        f"eye_x={s.eye_x_deg:.1f}° eye_y={s.eye_y_deg:.1f}°  "
        f"head_x={s.head_x_deg} head_y={s.head_y_deg}  "
        f"expr={s.expression}"
    )


def _sweep(robot: RobotController, axis_name: str) -> None:
    cfg = robot.config
    axis: ServoAxisConfig | None = getattr(cfg, axis_name, None)
    if axis is None or not isinstance(axis, ServoAxisConfig):
        raise ValueError(f"unknown axis {axis_name!r}")
    if not axis.enabled:
        print(f"{axis_name} is disabled in config")
        return
    print(f"sweeping {axis_name} pin={axis.pin} "
          f"[{axis.min_deg}, {axis.center_deg}, {axis.max_deg}] invert={axis.invert}")
    for angle in (axis.min_deg, axis.max_deg, axis.center_deg):
        robot.set_servo(axis_name, angle)
        print(f"  SET {axis_name}={angle:.1f}")


def run_repl(robot: RobotController) -> int:
    print("Robot calibration mode. Type 'help' for commands.")
    _print_state(robot)
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not raw:
            continue
        parts = raw.split()
        cmd = parts[0].lower()
        try:
            if cmd in {"q", "quit", "exit"}:
                break
            if cmd in {"h", "help", "?"}:
                print(HELP)
            elif cmd in {"left", "right", "up", "down", "center"}:
                robot.nudge(cmd)
                _print_state(robot)
            elif cmd == "look" and len(parts) == 3:
                robot.snap_look(float(parts[1]), float(parts[2]))
                _print_state(robot)
            elif cmd == "expr" and len(parts) >= 2:
                robot.set_expression(" ".join(parts[1:]))
                _print_state(robot)
            elif cmd == "set" and len(parts) == 3:
                robot.set_servo(parts[1], float(parts[2]))
                print(f"sent SET,{parts[1]},{float(parts[2]):.2f}")
            elif cmd == "sweep" and len(parts) == 2:
                _sweep(robot, parts[1])
            elif cmd == "ping":
                robot.ping()
                print("sent PING")
            elif cmd == "state":
                _print_state(robot)
                # Also show theoretical map at corners for calibration notes.
                for label, (x, y) in (
                    ("center", (0.5, 0.5)),
                    ("left", (0.0, 0.5)),
                    ("right", (1.0, 0.5)),
                    ("up", (0.5, 0.0)),
                    ("down", (0.5, 1.0)),
                ):
                    ex = norm_to_angle(x, robot.config.eye_x)
                    ey = norm_to_angle(y, robot.config.eye_y)
                    print(f"  map {label:6s} -> eye_x={ex:.1f} eye_y={ey:.1f}")
            else:
                print("Unknown command. Type 'help'.")
                if isinstance(robot.transport, MockTransport) and robot.transport.last:
                    print(f"(last wire) {robot.transport.last}")
                continue
            if isinstance(robot.transport, MockTransport) and robot.transport.last:
                print(f"(wire) {robot.transport.last}")
        except Exception as exc:  # noqa: BLE001 — REPL should keep running
            print(f"error: {exc}")
    return 0


def build_robot(args: argparse.Namespace) -> RobotController:
    cfg = RobotHardwareConfig.from_env()
    if args.port:
        cfg = cfg.with_updates(serial_port=args.port)
    if args.baud:
        cfg = cfg.with_updates(serial_baud=args.baud)
    if args.mock or not cfg.serial_port:
        if not args.mock and not cfg.serial_port:
            print("No serial port configured; using MockTransport. "
                  "Pass --port or set ROBOT_SERIAL_PORT.", file=sys.stderr)
        return RobotController(MockTransport(), cfg)
    return RobotController(
        SerialTransport(cfg.serial_port, cfg.serial_baud, cfg.serial_timeout),
        cfg,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibrate / test robot servos")
    parser.add_argument("--mock", action="store_true", help="use MockTransport (no hardware)")
    parser.add_argument("--port", default="", help="USB serial device path")
    parser.add_argument("--baud", type=int, default=0, help="serial baud (default 115200)")
    args = parser.parse_args(argv)
    robot = build_robot(args)
    try:
        return run_repl(robot)
    finally:
        robot.close()


if __name__ == "__main__":
    raise SystemExit(main())
