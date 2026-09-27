"""Run the existing Ottis camera/speech flow with bounded Uno servo rewards."""
from app.robot.camera_test import CameraServoTest
from test_ottis import main


if __name__ == '__main__':
    try:
        main(test_setup=CameraServoTest())
    except KeyboardInterrupt:
        pass
    except (RuntimeError, ValueError, OSError, ImportError) as exc:
        print(f'[CAMERA SERVO ERROR] {exc}')
        raise SystemExit(1)
