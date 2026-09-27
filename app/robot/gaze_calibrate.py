"""Robot-only CLI. See app/robot/GAZE_CALIBRATION.md for all three workflows."""
import argparse

from .factory import connect_robot
from .config import RobotHardwareConfig
from .gaze import GazeController, GazeMap, LABELS, EYES, LIFTS, load_axes, save_points

# Lowercase = 1 degree; uppercase = 5 degrees. Inversion sets jog direction.
JOG = {'a': ('eye_left', -1), 'd': ('eye_left', 1),
       'f': ('eye_right', -1), 'h': ('eye_right', 1),
       'j': ('neck', -1), 'l': ('neck', 1),
       'r': ('lift_left', -1), 'v': ('lift_left', 1),
       't': ('lift_right', -1), 'b': ('lift_right', 1)}
HELP = 'a/d eye L, f/h eye R | j/l neck | r/v lift L, t/b lift R'
PAIR_HELP = 'i/k pitch | u/o tilt | z/x both eyes | Shift=5deg | c center | q quit'


def state(controller):
    return '  '.join(f'{k}={v:.2f}deg' for k, v in controller.pose.items())


def jog(controller, key, world=False):
    if key == 'c':
        controller.center()
    elif key.lower() in 'ikuozx' and len(key) == 1:
        lower = key.lower()
        if world and lower in 'zx':
            return
        sign = -1 if lower in 'iuz' else 1
        controller.jog_pair(EYES if lower in 'zx' else LIFTS,
                            sign*(5 if key.isupper() else 1), differential=lower in 'uo')
    elif key.lower() in JOG:
        axis, sign = JOG[key.lower()]
        if not world or axis not in EYES:
            controller.jog(axis, sign*(5 if key.isupper() else 1))


def servo_limits(controller):
    print(HELP + '\n' + PAIR_HELP + '\nType a key then Enter. Edit your servo JSON after measuring safe limits.')
    while True:
        print(state(controller))
        try:
            key = input('servo> ').strip()
        except EOFError:
            return
        if key == 'q':
            return
        jog(controller, key)


def bottle(objects, frame):
    """YOLO supplies boxes/centers; blue pixel fraction only disambiguates bottles."""
    import cv2
    candidates = []
    for obj in objects:
        if obj.label.casefold() != 'bottle':
            continue
        x1, y1, x2, y2 = map(int, obj.bbox)
        crop = frame[y1:y2, x1:x2]
        if not crop.size:
            continue
        mask = cv2.inRange(cv2.cvtColor(crop, cv2.COLOR_BGR2HSV), (90, 60, 40), (135, 255, 255))
        fraction = cv2.countNonZero(mask)/mask.size
        if fraction >= .04:
            candidates.append(obj)
    # Never silently choose another bottle when the scene is ambiguous.
    return candidates[0] if len(candidates) == 1 else None


def camera_mode(controller, args):
    import cv2
    from app.vision.camera import Camera
    from app.vision.object_tracker import ObjectTracker
    tracker = ObjectTracker(model=args.model, device=args.device)
    points = []
    message = 'Place one blue bottle; Enter saves current detection and commanded pose.'
    print(HELP + '\n' + PAIR_HELP + '\nFocus the camera window for keys. Eyes stay centered in world mode.')
    try:
        with Camera(index=args.camera) as camera:
            while True:
                frame, _ = camera.read()
                target = bottle(tracker.update(frame), frame)
                if args.mode == 'track':
                    if target is not None:
                        controller.look_at(*target.center_normalized)
                    else:
                        controller.hold()
                if target is not None:
                    x1, y1, x2, y2 = map(int, target.bbox)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
                label = LABELS[len(points)] if args.mode == 'world' else 'tracking'
                lines = (label,
                         '  '.join(f'{k}={controller.pose[k]:.2f}' for k in EYES),
                         '  '.join(f'{k}={controller.pose[k]:.2f}' for k in ('neck', *LIFTS)),
                         'Bottle: ' + (str(tuple(round(v, 3) for v in target.center_normalized))
                                       if target else 'missing/ambiguous; cannot save'),
                         message, HELP, PAIR_HELP)
                for row, text in enumerate(lines):
                    cv2.putText(frame, text, (8, 22+24*row), cv2.FONT_HERSHEY_SIMPLEX, .42, (0, 255, 255), 1)
                cv2.imshow('Robot gaze (unmirrored)', frame)
                key = cv2.waitKey(1) & 0xff
                if key == ord('q') or cv2.getWindowProperty('Robot gaze (unmirrored)', cv2.WND_PROP_VISIBLE) < 1:
                    return
                if args.mode == 'world':
                    jog(controller, chr(key), world=True)
                    if key in (10, 13) and target is not None:
                        x, y = target.center_normalized
                        if any((x-p['camera_x'])**2+(y-p['camera_y'])**2 < .02**2 for p in points):
                            message = 'Too close to another sample; move bottle farther.'
                            continue
                        point = dict(label=label, camera_x=x, camera_y=y,
                                     neck_angle=controller.pose['neck'],
                                     lift_left_angle=controller.pose['lift_left'],
                                     lift_right_angle=controller.pose['lift_right'])
                        proposed = points + [point]
                        if len(proposed) == len(LABELS):
                            try:
                                GazeMap(proposed)
                            except ValueError as exc:
                                message = str(exc)
                                continue
                        points = proposed
                        save_points(args.calibration, controller.axes, points)
                        print(f'Saved {label}: {point}')
                        if len(points) == len(LABELS):
                            print('World calibration complete:', args.calibration)
                            return
                        message = 'Saved. Move bottle to ' + LABELS[len(points)]
    finally:
        cv2.destroyAllWindows()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('limits', 'world', 'track'))
    parser.add_argument('--servos', default='config/robot-servos.json')
    parser.add_argument('--calibration', default='config/robot-gaze.json')
    parser.add_argument('--port', help='USB serial port (or ROBOT_SERIAL_PORT)')
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--mock', action='store_true')
    parser.add_argument('--camera', type=int, default=0)
    parser.add_argument('--model', default=None)
    parser.add_argument('--device', default='auto')
    args = parser.parse_args(argv)
    axes = load_axes(args.servos)
    calibration = GazeMap.load(args.calibration, axes) if args.mode == 'track' else None
    cfg = RobotHardwareConfig.from_env().with_updates(serial_baud=args.baud)
    with connect_robot(cfg, transport='serial', serial_port=args.port, mock=args.mock) as robot:
        controller = GazeController(robot, axes, calibration)
        controller.initialize()
        try:
            if args.mode == 'limits':
                servo_limits(controller)
            else:
                camera_mode(controller, args)
        except KeyboardInterrupt:
            pass  # Hold the last bounded pose, without an unexpected return sweep.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
