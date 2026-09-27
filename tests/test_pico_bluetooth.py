"""Offline BLE lifecycle, framing, and Pico firmware motion tests."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.robot.config import RobotHardwareConfig
from app.robot.transport.bluetooth import BluetoothTransport


class FakeClient:
    instances = []

    def __init__(self, device, **kwargs):
        self.is_connected = False
        self.writes = []
        self.fail = False
        self.services = SimpleNamespace(get_characteristic=lambda uuid: object())
        self.instances.append(self)

    async def connect(self):
        self.is_connected = True

    async def disconnect(self):
        self.is_connected = False

    async def start_notify(self, uuid, callback):
        self.callback = callback

    async def write_gatt_char(self, uuid, data, response):
        if self.fail:
            raise ConnectionError("lost link")
        assert response
        self.writes.append(data)


class FakeScanner:
    @staticmethod
    async def find_device_by_filter(predicate, **kwargs):
        assert "service_uuids" not in kwargs
        device = SimpleNamespace(address="test")
        return device if predicate(device, SimpleNamespace(local_name="PicoRobot")) else None

    @staticmethod
    async def find_device_by_address(address, **kwargs):
        assert "service_uuids" not in kwargs
        return SimpleNamespace(address=address)


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        self.mock = patch.dict(sys.modules, bleak=SimpleNamespace(
            BleakClient=FakeClient, BleakScanner=FakeScanner))
        self.mock.start()
        self.link = BluetoothTransport(timeout=0.1)
        self.addCleanup(self.mock.stop)
        self.addCleanup(self.link.close)

    def test_fragment_and_reply(self):
        self.link.open()
        client = self.link._client
        self.link.open()
        self.assertIs(client, self.link._client)
        command = "LOOK,0.1234,0.5678,0.5000,0.5000"
        self.link.send_line(command)
        self.assertEqual(b"".join(client.writes), (command + "\n").encode())
        self.assertTrue(all(len(chunk) <= 20 for chunk in client.writes))
        client.callback(None, b"PO")
        client.callback(None, b"NG\nACK,LOOK\n")
        self.assertEqual(self.link.recv_line(0), "PONG")
        self.assertEqual(self.link.recv_line(0), "ACK,LOOK")
        with self.assertRaises(ValueError):
            self.link.send_line("PING\nCENTER")

    def test_failure_closes_and_does_not_replay(self):
        self.link.open()
        client = self.link._client
        client.fail = True
        with self.assertRaises(ConnectionError):
            self.link.send_line("CENTER")
        self.assertFalse(self.link.is_open())
        self.assertIsNone(self.link._thread)
        self.assertEqual(client.writes, [])

    def test_not_found_cleans_thread(self):
        self.link.name = "missing"
        with self.assertRaises(ConnectionError):
            self.link.open()
        self.assertIsNone(self.link._thread)

    def test_explicit_address_does_not_filter_advertised_service(self):
        self.link.address = "test-address"
        self.link.open()
        self.assertTrue(self.link.is_open())

    def test_incompatible_firmware_disconnects_before_sending(self):
        class OtherServices(list):
            def get_characteristic(self, uuid):
                return None

        original_connect = FakeClient.connect

        async def connect_other(client):
            await original_connect(client)
            client.services = OtherServices()

        with patch.object(FakeClient, "connect", connect_other):
            with self.assertRaisesRegex(ConnectionError, "different BLE protocol"):
                self.link.open()
        self.assertIsNone(self.link._thread)
        self.assertEqual(FakeClient.instances[-1].writes, [])

    def test_factory_routes_controller_motion(self):
        from app.robot import connect_robot
        with connect_robot(RobotHardwareConfig(transport="bluetooth")) as robot:
            robot.snap_look(0.7, 0.3)
            self.assertEqual(b"".join(robot.transport._client.writes),
                             b"LOOK,0.7000,0.3000\n")
        with connect_robot(RobotHardwareConfig(), mock=True) as robot:
            robot.ping()
            self.assertEqual(robot.transport.last, "PING")

    def test_config(self):
        self.assertEqual(RobotHardwareConfig().resolved_transport(), "bluetooth")
        self.assertEqual(RobotHardwareConfig(transport="mock").resolved_transport(), "mock")
        with self.assertRaises(ValueError):
            RobotHardwareConfig(bluetooth_timeout=0)


class FirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "firmware/robot_controller_pico_w/main.py"
        spec = importlib.util.spec_from_file_location("pico_firmware", path)
        cls.fw = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, bluetooth=SimpleNamespace(UUID=lambda x: x),
                        machine=SimpleNamespace(Pin=object, PWM=object)):
            spec.loader.exec_module(cls.fw)
        cls.fw.LED_TEST_MODE = True

    def test_fragmentation_and_overflow(self):
        buffer = self.fw.LineBuffer()
        self.assertEqual(buffer.feed(b"LOOK,0.2"), [])
        self.assertEqual(buffer.feed(b",0.3\nPING\n"), ["LOOK,0.2,0.3", "PING"])
        self.assertEqual(buffer.feed(b"a" * 100 + b"CENTER\nPING\n"), ["PING"])

    def test_commands_and_limits(self):
        motion = self.fw.Motion()
        self.assertEqual(motion.command("PING"), "PONG")
        self.assertEqual(motion.command("LOOK,1,0,0.2,0.8"), "ACK,LOOK")
        self.assertEqual(motion.axes["eye_x"].target, 120)
        self.assertEqual(motion.axes["eye_y"].target, 60)
        self.assertEqual(motion.command("SET,eye_x,999"), "ACK,SET")
        self.assertEqual(motion.axes["eye_x"].target, 120)
        self.assertEqual(motion.command("SET,head_x,100"), "ERR,disabled")
        self.assertEqual(motion.command("LOOK,0.5,nan"), "ERR,argument")
        self.assertEqual(motion.x, 1)
        self.assertEqual(motion.command("MOVE,LEFT"), "ACK,MOVE")
        self.assertAlmostEqual(motion.x, 0.85)
        motion.command("CENTER")
        self.assertTrue(all(axis.target == axis.center for axis in motion.axes.values()))
        self.assertEqual(motion.command("EXPR,happy"), "ACK,EXPR")
        self.assertEqual(motion.expression, "happy")

    def test_packet_mode_never_initializes_pwm(self):
        from unittest.mock import Mock
        pin, pwm = Mock(), Mock()
        with patch.object(self.fw, "Pin", pin), patch.object(self.fw, "PWM", pwm):
            motion = self.fw.Motion()
            before = [(a.current, a.target) for a in motion.axes.values()]
            payload = "ECHO,hello,pi with a payload longer than twenty bytes"
            self.assertEqual(motion.command(payload), payload)
            self.assertEqual(motion.command("PING"), "PONG")
            self.assertEqual(before, [(a.current, a.target) for a in motion.axes.values()])
            motion.center()
            for axis in motion.axes.values():
                axis.step()
            pin.assert_not_called()
            pwm.assert_not_called()

    def test_echo_notifications_reassemble(self):
        from test_pico import exchange
        link = BluetoothTransport()
        peripheral = self.fw.RobotBLE.__new__(self.fw.RobotBLE)
        peripheral.connection, peripheral.tx = 1, 2
        chunks = []

        def notify(connection, handle, data):
            chunks.append(data)
            link._notify(handle, data)

        peripheral.ble = SimpleNamespace(gatts_notify=notify)
        motion = self.fw.Motion()
        buffer = self.fw.LineBuffer()

        def send(line):
            data = (line + "\n").encode()
            for offset in range(0, len(data), 20):
                for command in buffer.feed(data[offset:offset + 20]):
                    peripheral.reply(motion.command(command))

        link.send_line = send
        message = "ECHO," + "x" * 90
        exchange(link, message, message, timeout=0)
        self.assertTrue(all(len(chunk) <= 20 for chunk in chunks))
        exchange(link, "PING", "PONG", timeout=0)
        with self.assertRaises(RuntimeError):
            exchange(link, "PING", "wrong", timeout=0)


if __name__ == "__main__":
    unittest.main()
