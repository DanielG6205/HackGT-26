"""Offline unit tests for the robot control layer (no hardware)."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.robot import (
    MockTransport,
    RobotController,
    RobotHardwareConfig,
    ServoAxisConfig,
    WifiTransport,
)
from app.robot.mapping import apply_deadzone, clamp01, norm_to_angle, step_toward
from app.robot.protocol import (
    encode_center,
    encode_expression,
    encode_look,
    encode_move,
    encode_set_axis,
    parse_command,
)


class MappingTests(unittest.TestCase):
    def test_norm_to_angle_center_and_ends(self):
        axis = ServoAxisConfig(pin=9, center_deg=90, min_deg=60, max_deg=120)
        self.assertAlmostEqual(norm_to_angle(0.5, axis), 90)
        self.assertAlmostEqual(norm_to_angle(0.0, axis), 60)
        self.assertAlmostEqual(norm_to_angle(1.0, axis), 120)

    def test_invert_and_clamp(self):
        axis = ServoAxisConfig(pin=9, center_deg=90, min_deg=60, max_deg=120, invert=True)
        self.assertAlmostEqual(norm_to_angle(0.0, axis), 120)
        self.assertAlmostEqual(norm_to_angle(1.0, axis), 60)
        self.assertEqual(clamp01(1.5), 1.0)
        self.assertEqual(clamp01(-0.2), 0.0)

    def test_deadzone_and_step(self):
        self.assertFalse(apply_deadzone(0.51, 0.50, 0.50, 0.50, 0.02))
        self.assertTrue(apply_deadzone(0.53, 0.50, 0.50, 0.50, 0.02))
        self.assertAlmostEqual(step_toward(0.0, 1.0, 0.25), 0.25)
        self.assertAlmostEqual(step_toward(0.9, 1.0, 0.25), 1.0)


class ProtocolTests(unittest.TestCase):
    def test_encode_roundtrip_shapes(self):
        self.assertEqual(encode_look(0.72, 0.41), "LOOK,0.7200,0.4100")
        self.assertEqual(encode_look(0.7, 0.4, 0.5, 0.55), "LOOK,0.7000,0.4000,0.5000,0.5500")
        self.assertEqual(encode_center(), "CENTER")
        self.assertEqual(encode_expression("Happy Face"), "EXPR,happy_face")
        self.assertEqual(encode_move("left"), "MOVE,LEFT")
        self.assertEqual(encode_set_axis("eye_x", 95), "SET,eye_x,95.00")
        cmd = parse_command("LOOK,0.72,0.41\n")
        self.assertEqual(cmd.name, "LOOK")
        self.assertEqual(cmd.args, ("0.72", "0.41"))


class ControllerTests(unittest.TestCase):
    def test_look_at_sends_protocol_and_maps_angles(self):
        transport = MockTransport()
        robot = RobotController(transport, RobotHardwareConfig(deadzone=0.0))
        state = robot.look_at(0.72, 0.41)
        self.assertEqual(transport.last, "LOOK,0.7200,0.4100")
        self.assertAlmostEqual(state.x, 0.72)
        self.assertAlmostEqual(state.y, 0.41)
        self.assertGreater(state.eye_x_deg, 90)
        self.assertLess(state.eye_y_deg, 90)  # y down from center → below if not inverted... 
        # y=0.41 is above center (0.5), so eye_y should be below center angle when not inverted
        # norm 0.41 < 0.5 → between min and center
        self.assertLess(state.eye_y_deg, 90)

    def test_deadzone_suppresses_tiny_jitter(self):
        clock = MagicMock(side_effect=[0.0, 1.0, 2.0])
        transport = MockTransport()
        cfg = RobotHardwareConfig(deadzone=0.05, max_look_speed=100.0)
        robot = RobotController(transport, cfg, clock=clock)
        robot.look_at(0.50, 0.50)
        transport.clear()
        robot.look_at(0.52, 0.50)  # delta 0.02 < deadzone 0.05
        self.assertIsNone(transport.last)
        robot.look_at(0.60, 0.50)
        self.assertEqual(transport.last, "LOOK,0.6000,0.5000")

    def test_speed_limit_smooths_large_jumps(self):
        times = iter([0.0, 0.1, 0.2])
        transport = MockTransport()
        cfg = RobotHardwareConfig(deadzone=0.0, max_look_speed=1.0)  # 0.1 units per 0.1s
        robot = RobotController(transport, cfg, clock=lambda: next(times))
        # First call adopts immediately (no prior timestamp).
        robot.look_at(0.0, 0.5)
        self.assertEqual(transport.lines[-1], "LOOK,0.0000,0.5000")
        # Reset to center then move with speed limit.
        robot.center_eyes()
        # Manually set clock sequence again with a fresh controller for clarity.
        clock = MagicMock(side_effect=[1.0, 1.1, 1.2, 1.3])
        transport = MockTransport()
        robot = RobotController(transport, cfg, clock=clock)
        robot.look_at(0.5, 0.5)  # t=1.0 adopt center
        transport.clear()
        robot.look_at(1.0, 0.5)  # t=1.1 → move +0.1
        self.assertEqual(transport.last, "LOOK,0.6000,0.5000")
        robot.flush()  # t=1.2 → +0.1 → 0.7
        self.assertEqual(transport.last, "LOOK,0.7000,0.5000")

    def test_look_at_user_object_center_expression(self):
        clock = MagicMock(side_effect=[0.0, 10.0, 20.0, 30.0, 40.0])
        transport = MockTransport()
        cfg = RobotHardwareConfig(deadzone=0.0, max_look_speed=10.0)
        robot = RobotController(transport, cfg, clock=clock)
        face = SimpleNamespace(face_center=(0.3, 0.4))
        obj = SimpleNamespace(center_normalized=(0.8, 0.2))
        robot.look_at_user(face)
        self.assertTrue(transport.last.startswith("LOOK,0.3000,0.4000"))
        robot.look_at_object(obj)
        self.assertTrue(transport.lines[-1].startswith("LOOK,0.8000,0.2000"))
        robot.center_eyes()
        self.assertEqual(transport.last, "CENTER")
        robot.set_expression("Happy")
        self.assertEqual(transport.last, "EXPR,happy")
        robot.look_at_user()  # uses cached face
        self.assertTrue(transport.last.startswith("LOOK,0.3000,0.4000"))

    def test_head_coupling_and_wifi_tcp(self):
        cfg = RobotHardwareConfig(
            head_x=ServoAxisConfig(pin=5, enabled=True),
            head_y=ServoAxisConfig(pin=6, enabled=True),
            couple_head_to_look=True,
            deadzone=0.0,
        )
        transport = MockTransport()
        robot = RobotController(transport, cfg)
        robot.look_at(0.7, 0.3)
        self.assertEqual(transport.last, "LOOK,0.7000,0.3000,0.7000,0.3000")
        self.assertIsNotNone(robot.state.head_x_deg)

        # Local TCP echo-ish acceptor for WifiTransport.
        import socket
        import threading

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        host, port = server.getsockname()
        received = []

        def accept_once():
            conn, _ = server.accept()
            with conn:
                data = conn.recv(256)
                received.append(data)

        worker = threading.Thread(target=accept_once, daemon=True)
        worker.start()
        wifi = WifiTransport(host, port, timeout=1.0, connect_retries=3, retry_delay=0.05)
        wifi.open()
        wifi.send_line("PING")
        worker.join(2)
        wifi.close()
        server.close()
        self.assertTrue(received)
        self.assertEqual(received[0], b"PING\n")

    def test_nudge_and_set_servo(self):
        transport = MockTransport()
        robot = RobotController(transport, RobotHardwareConfig(calibration_step=0.1, deadzone=0.0))
        robot.nudge("LEFT")
        self.assertIn("MOVE,LEFT", transport.lines)
        self.assertTrue(any(l.startswith("LOOK,") for l in transport.lines))
        robot.set_servo("eye_x", 100)
        self.assertEqual(transport.last, "SET,eye_x,100.00")


if __name__ == "__main__":
    unittest.main()
