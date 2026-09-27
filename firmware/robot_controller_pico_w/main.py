"""Copy to Pico W as main.py using MicroPython with Bluetooth support."""
import bluetooth
import math
import time
from machine import Pin, PWM

NAME = "PicoRobot"
# Leave enabled until the seven servo connections have been identified.
# No PWM is created, including at startup and on Bluetooth disconnect.
LED_TEST_MODE = True
# GPIO numbers, NOT physical header positions. Match app/robot/config.py.
# name: (GPIO, center, minimum, maximum, inverted, enabled)
AXES = {
    "eye_x": (18, 90, 60, 120, False, True),
    "eye_y": (19, 90, 60, 120, False, True),
    "head_x": (21, 90, 60, 120, False, False),
    "head_y": (22, 90, 60, 120, False, False),
}
SERVICE_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
RX_UUID = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
TX_UUID = bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")


def clamp(value, low, high):
    return max(low, min(high, value))


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite number")
    return result


class Axis:
    def __init__(self, config):
        pin, self.center, self.low, self.high, self.invert, self.enabled = config
        self.current = self.target = self.center
        self.pwm = PWM(Pin(pin), freq=50) if self.enabled and not LED_TEST_MODE else None
        self.step()

    def look(self, value):
        value = clamp(value, 0, 1)
        if self.invert:
            value = 1 - value
        self.target = (self.low + value * 2 * (self.center - self.low)
                       if value <= 0.5 else
                       self.center + (value - 0.5) * 2 * (self.high - self.center))

    def step(self):
        self.current += (self.target - self.current) * 0.05
        self.current = clamp(self.current, self.low, self.high)
        if self.pwm:
            # Preserve existing 1000–2000 us mapping; calibrate for your servo.
            self.pwm.duty_ns(int((1000 + self.current / 180 * 1000) * 1000))


class Motion:
    def __init__(self):
        self.axes = {name: Axis(config) for name, config in AXES.items()}
        self.x = self.y = 0.5
        self.expression = "neutral"

    def center(self):
        self.x = self.y = 0.5
        for axis in self.axes.values():
            axis.target = axis.center

    def look(self, x, y):
        self.x, self.y = clamp(x, 0, 1), clamp(y, 0, 1)
        self.axes["eye_x"].look(self.x)
        self.axes["eye_y"].look(self.y)

    def command(self, line):
        # Preserve payload exactly; this command never changes motion state.
        if line.startswith("ECHO,"):
            return line
        parts = [part.strip() for part in line.split(",")]
        cmd, args = parts[0].upper(), parts[1:]
        try:
            if cmd == "PING" and not args:
                return "PONG"
            if cmd == "CENTER" and not args:
                self.center()
            elif cmd == "LOOK" and len(args) in (2, 4):
                values = [number(arg) for arg in args]  # validate before moving
                self.look(*values[:2])
                if len(values) == 4:
                    self.axes["head_x"].look(values[2])
                    self.axes["head_y"].look(values[3])
            elif cmd == "SET" and len(args) == 2 and args[0] in self.axes:
                axis = self.axes[args[0]]
                value = number(args[1])
                if not axis.enabled:
                    return "ERR,disabled"
                axis.target = clamp(value, axis.low, axis.high)
            elif cmd == "MOVE" and len(args) == 1:
                direction = args[0].upper()
                if direction == "CENTER":
                    self.center()
                else:
                    dx, dy = {"LEFT": (-0.15, 0), "RIGHT": (0.15, 0),
                              "UP": (0, -0.15), "DOWN": (0, 0.15)}[direction]
                    self.look(self.x + dx, self.y + dy)
            elif cmd == "EXPR" and len(args) == 1 and args[0]:
                # Hook for future eyelid/display hardware; no audio is received.
                self.expression = args[0]
            else:
                return "ERR,command"
        except (ValueError, KeyError):
            return "ERR,argument"
        return "ACK," + cmd


class LineBuffer:
    """Reassemble BLE fragments; discard oversized commands through newline."""
    def __init__(self):
        self.data = bytearray()
        self.discard = False

    def feed(self, data):
        lines = []
        for byte in data:
            if byte == 10:
                if self.data and not self.discard:
                    try:
                        lines.append(self.data.decode("ascii").strip())
                    except UnicodeError:
                        pass
                self.data = bytearray()
                self.discard = False
            elif not self.discard:
                self.data.append(byte)
                if len(self.data) > 95:
                    self.data = bytearray()
                    self.discard = True
        return lines


class RobotBLE:
    def __init__(self):
        self.motion = Motion()
        self.lines = LineBuffer()
        self.connection = None
        self.reset = False
        self.led = Pin("LED", Pin.OUT)
        self.led_until = time.ticks_ms()
        self.ble = bluetooth.BLE()
        self.ble.active(True)
        ((self.tx, self.rx),) = self.ble.gatts_register_services(((SERVICE_UUID, (
            (TX_UUID, bluetooth.FLAG_NOTIFY), (RX_UUID, bluetooth.FLAG_WRITE))),))
        self.ble.gatts_set_buffer(self.rx, 512, True)
        self.ble.irq(self.irq)
        # Flags and complete 128-bit service UUID in advertisement; name in scan response.
        self.advertisement = b"\x02\x01\x06\x11\x07" + bytes(SERVICE_UUID)
        name = NAME.encode()
        self.scan_response = bytes((len(name) + 1, 9)) + name
        self.advertise()

    def advertise(self):
        self.ble.gap_advertise(100_000, adv_data=self.advertisement,
                               resp_data=self.scan_response)

    def irq(self, event, data):
        if event == 1:  # central connected
            self.connection = data[0]
        elif event == 2:  # central disconnected
            self.connection = None
            self.reset = True
        # RX uses append mode; the main loop drains it, outside the IRQ.

    def reply(self, line):
        if self.connection is not None:
            try:
                payload = (line + "\n").encode()
                for offset in range(0, len(payload), 20):
                    self.ble.gatts_notify(self.connection, self.tx, payload[offset:offset + 20])
            except OSError:
                pass  # notifications are diagnostic, never block servo updates

    def run(self):
        while True:
            if self.reset:
                self.motion.center()
                self.lines = LineBuffer()
                self.ble.gatts_read(self.rx)
                self.reset = False
                self.advertise()
            data = self.ble.gatts_read(self.rx)
            if data and self.connection is not None:
                for line in self.lines.feed(data):
                    self.reply(self.motion.command(line))
                    self.led_until = time.ticks_add(time.ticks_ms(), 100)
            self.led.value(time.ticks_diff(self.led_until, time.ticks_ms()) > 0)
            for axis in self.motion.axes.values():
                axis.step()
            time.sleep_ms(5)


if __name__ == "__main__":
    RobotBLE().run()
