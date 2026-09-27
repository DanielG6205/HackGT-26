"""Send numeric angles over USB serial or BLE to compatible seven-servo firmware."""
import argparse
import re

from app.robot import connect_robot, RobotHardwareConfig
from app.robot.transport.serial_transport import wait_for_reply


def parse_angle(value):
    try:
        angle = int(value)
    except ValueError:
        raise ValueError("Enter a whole number from 0 to 180, or q to quit.") from None
    if not 0 <= angle <= 180:
        raise ValueError("Angle must be between 0 and 180.")
    return str(angle)


def parse_uno_command(value):
    if not re.fullmatch(r"[1-7]\s*,\s*[0-9]{1,3}", value):
        raise ValueError("Enter servo,angle (servo 1-7; angle 0-180), e.g. 1,95.")
    servo, angle = value.split(",")
    return f"{int(servo)},{parse_angle(angle)}"


def run_uno(args):
    from contextlib import nullcontext
    import serial

    print("Uno: servo 1-7 maps to pins 10,9,8,7,6,5,4.")
    print("Opening USB may reset the Uno: your sketch centers ALL servos at 90 degrees.")
    print("Enter servo,angle (e.g. 1,95). q quits without sending another position.")
    context = nullcontext(None) if args.mock else serial.Serial(
        args.port, args.baud, timeout=0.1, write_timeout=1)
    with context as port:
        if port is not None:
            print(wait_for_reply(port, "READY", timeout=5))
        while True:
            try:
                value = input("servo,angle or q: ").strip()
            except EOFError:
                break
            if value.lower() in ("q", "quit", "exit"):
                break
            try:
                command = parse_uno_command(value)
            except ValueError as exc:
                print(exc)
                continue
            if port is None:
                print(f"MOCK TX {command!r}; no hardware tested")
            else:
                port.write((command + "\n").encode("ascii"))
                port.flush()
                print(wait_for_reply(port, "OK," + command))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="Pico-Servos")
    parser.add_argument("--address", help="BLE address or macOS UUID")
    parser.add_argument("--mock", action="store_true", help="Preview without hardware")
    parser.add_argument("--port", help="Uno USB serial port; selects serial instead of BLE")
    parser.add_argument("--baud", type=int, default=115200, help="Must match the Uno sketch (default: 115200)")
    parser.add_argument("--list-ports", action="store_true", help="List USB serial ports and exit")
    args = parser.parse_args(argv)
    if args.list_ports:
        from serial.tools.list_ports import comports
        ports = list(comports())
        for port in ports:
            print(f"{port.device}  {port.description}")
        if not ports:
            print("No serial ports found. Connect the Uno with a USB data cable.")
        return
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.port:
        try:
            run_uno(args)
        except KeyboardInterrupt:
            print("\nStopped.")
        except (ImportError, OSError, RuntimeError) as exc:
            parser.exit(1, f"Uno test failed: {exc}\n")
        return
    print("Each angle moves ALL SEVEN servos. No position is sent automatically.")
    print("Use small changes from the current position; q quits without repositioning.")
    try:
        with connect_robot(RobotHardwareConfig.from_env().with_updates(serial_baud=args.baud),
                           transport="bluetooth", mock=args.mock,
                           bluetooth_name=args.name,
                           bluetooth_address=args.address) as robot:
            print("Mock mode." if args.mock else "Connected via Bluetooth.")
            while True:
                try:
                    value = input("All servos angle [0-180], or q: ").strip()
                except EOFError:
                    break
                if value.lower() in ("q", "quit", "exit"):
                    break
                try:
                    command = parse_angle(value)
                except ValueError as exc:
                    print(exc)
                    continue
                # At most four bytes including newline: one BLE write, matching
                # the friend's per-write parser. It sends no application replies.
                robot.transport.send_line(command)
                print(f"MOCK: would send {command} degrees to all seven servos."
                      if args.mock else
                      f"Sent {command} degrees to all seven servos "
                      "(GATT acknowledged; movement not verified).")
    except KeyboardInterrupt:
        print("\nStopped.")
    except (ImportError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Servo connection failed: {exc}\n")


if __name__ == "__main__":
    main()
