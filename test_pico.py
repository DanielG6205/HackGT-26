"""Manual Pico W BLE smoke test; audio stays on the computer."""
import argparse
import time
from app.robot import connect_robot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--name", default=None)
    parser.add_argument("--address", default=None, help="BLE address or macOS UUID")
    args = parser.parse_args()
    with connect_robot(transport="bluetooth", mock=args.mock,
                       bluetooth_name=args.name, bluetooth_address=args.address) as robot:
        robot.ping()
        if not args.mock:
            reply = robot.transport.recv_line(timeout=3)
            if reply != "PONG":
                raise RuntimeError(f"Expected Pico PONG, received {reply!r}")
            print("Pico replied PONG over Bluetooth")
        try:
            for x, y in ((0.5, 0.5), (0.35, 0.5), (0.65, 0.5), (0.5, 0.35), (0.5, 0.65)):
                robot.snap_look(x, y)
                print(f"LOOK {x}, {y}")
                time.sleep(1)
        finally:
            robot.center_eyes()
            time.sleep(0.5)


if __name__ == "__main__":
    main()
