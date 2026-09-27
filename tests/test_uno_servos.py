"""Checks for the Uno's numbered-servo serial protocol."""
import unittest
from test_servos import parse_uno_command
from app.robot.transport.serial_transport import wait_for_reply


class FakeSerial:
    in_waiting = 0

    def __init__(self, data):
        self.data = bytearray(data)

    def read(self, size):
        result = self.data[:size]
        del self.data[:size]
        return result


class UnoTests(unittest.TestCase):
    def test_numbered_commands(self):
        for value, expected in (("1,0", "1,0"), ("7,180", "7,180"), ("2 , 095", "2,95")):
            self.assertEqual(parse_uno_command(value), expected)
        for value in ("90", "0,90", "8,90", "1,-1", "1,181", "1,abc", "1,90,2", "1,9.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_uno_command(value)

    def test_fragmented_ack(self):
        self.assertEqual(wait_for_reply(FakeSerial(b"READY\r\nOK,1,95\r\n"), "OK,1,95"), "OK,1,95")

    def test_wrong_ack_or_error_fails(self):
        for data in (b"ERROR angle\n", b"OK,2,95\n"):
            with self.assertRaises(RuntimeError):
                wait_for_reply(FakeSerial(data), "OK,1,95")

    def test_no_reply_fails(self):
        with self.assertRaises(TimeoutError):
            wait_for_reply(FakeSerial(b""), "READY", timeout=0.001)
