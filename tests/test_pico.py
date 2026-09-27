"""Pico W BLE packet test. Sends no servo movement commands."""
import argparse
import asyncio
import time
from app.robot import connect_robot
from app.robot.transport.bluetooth import SERVICE_UUID


async def scan_devices():
    from bleak import BleakScanner

    print("Scanning nearby BLE devices for 10 seconds (no connections or packets)...")
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    for device, advertisement in sorted(devices.values(), key=lambda item: item[0].address):
        name = advertisement.local_name or device.name or "(unnamed)"
        matches = SERVICE_UUID in [uuid.lower() for uuid in advertisement.service_uuids]
        print(f"{device.address}  {name!r}" + ("  [robot UART service]" if matches else ""))
    if not devices:
        print("No devices found. Check Bluetooth access and that the Pico is advertising.")
    else:
        print("Identify your Pico by scanning with it powered off, then on.")
        print('Connect with: .venv/bin/python test_pico.py --address "ADDRESS" --count 5')
        print("Packet testing requires your friend's firmware to use the same UART UUIDs and PING/PONG protocol.")


def exchange(link, command, expected, timeout=3):
    start = time.monotonic()
    link.send_line(command)
    reply = link.recv_line(timeout=timeout)
    if reply != expected:
        raise RuntimeError(f"Sent {command!r}; expected {expected!r}, received {reply!r}")
    return (time.monotonic() - start) * 1000


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scan", action="store_true", help="List nearby BLE devices without connecting")
    parser.add_argument("--mock", action="store_true", help="Preview packets without Bluetooth")
    parser.add_argument("--name", default=None)
    parser.add_argument("--address", default=None, help="BLE address or macOS UUID")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--send-only", action="store_true",
                        help="Send PING without waiting for PONG; verify receipt in the Pico console")
    parser.add_argument("--message", help="Also echo ASCII text back (requires updated firmware)")
    args = parser.parse_args(argv)
    if args.scan:
        try:
            asyncio.run(scan_devices())
        except (ImportError, OSError, RuntimeError) as exc:
            parser.exit(1, f"Bluetooth scan failed: {exc}\n")
        return
    if args.count < 1:
        parser.error("--count must be positive")
    if args.send_only and args.message is not None:
        parser.error("--send-only supports only PING; omit --message")
    if args.message is not None:
        if (not args.message.isascii() or any(c in args.message for c in "\r\n")
                or len(args.message) > 90 or args.message != args.message.strip()):
            parser.error("--message must be at most 90 ASCII characters, one line, with no outer whitespace")
    packets = [("PING", "PONG")]
    if args.message is not None:
        packets.append(("ECHO," + args.message, "ECHO," + args.message))
    print("Packet-only test: sends PING" + (" and ECHO" if args.message is not None else "")
          + "; no movement commands.")
    try:
        with connect_robot(transport="bluetooth", mock=args.mock,
                           bluetooth_name=args.name, bluetooth_address=args.address) as robot:
            for index in range(args.count):
                for command, expected in packets:
                    if args.mock:
                        robot.transport.send_line(command)
                        print(f"MOCK TX {command!r} (no hardware reply)")
                    elif args.send_only:
                        robot.transport.send_line(command)
                        print(f"[{index + 1}/{args.count}] TX {command!r}: GATT write acknowledged")
                        time.sleep(0.5)
                    else:
                        elapsed = exchange(robot.transport, command, expected)
                        print(f"[{index + 1}/{args.count}] TX {command!r} -> RX {expected!r} ({elapsed:.0f} ms)")
            if args.mock:
                print("Mock preview complete; Bluetooth not tested.")
            elif args.send_only:
                print("Writes completed; no application reply checked. Confirm 'Received: PING' in the Pico console.")
            else:
                print("PASS: all packets received matching replies over Bluetooth.")
    except (ImportError, OSError, RuntimeError) as exc:
        parser.exit(1, f"Bluetooth test failed: {exc}\n"
                    "Check board firmware, Bluetooth access, and that no other app is connected.\n")


if __name__ == "__main__":
    main()
