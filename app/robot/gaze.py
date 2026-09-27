"""Five-servo physical-angle calibration and deterministic gaze motion."""
import json
import math
import time
from dataclasses import asdict
from pathlib import Path

from .config import ServoAxisConfig
from .mapping import step_toward

AXES = ('eye_left', 'eye_right', 'neck', 'lift_left', 'lift_right')
EYES = ('eye_left', 'eye_right')
LIFTS = ('lift_left', 'lift_right')
LABELS = ('top-left', 'top-center', 'top-right', 'middle-left', 'center',
          'middle-right', 'bottom-left', 'bottom-center', 'bottom-right')


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Angles and coordinates must be finite')
    return value


def load_axes(path):
    data = json.loads(Path(path).read_text())
    if set(data) != set(AXES):
        raise ValueError('Expected five servos: ' + ', '.join(AXES) + '; update the old three-axis config')
    axes = {name: ServoAxisConfig(**data[name]) for name in AXES}
    pins = [axis.pin for axis in axes.values()]
    if len(set(pins)) != len(AXES) or any(p not in range(2, 14) for p in pins):
        raise ValueError('Use five distinct Uno digital pins 2..13')
    if any(p in (6, 7) for p in pins):
        raise ValueError('Pins 6 and 7 are reserved for Arduino-controlled eyelids')
    if any(not a.enabled or not 0 <= a.min_deg <= a.max_deg <= 180 for a in axes.values()):
        raise ValueError('All five servos must be enabled with limits within 0..180')
    if any(math.ceil(a.min_deg*10000) > math.floor(a.max_deg*10000) for a in axes.values()):
        raise ValueError('Servo limits must allow a representable four-decimal angle')
    return axes


def save_points(path, axes, points):
    """Atomic checkpoint after every capture, including incomplete sessions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps({'version': 2, 'axes': {k: asdict(v) for k, v in axes.items()},
                                     'points': points}, indent=2) + '\n')
    temporary.replace(path)


class GazeMap:
    def __init__(self, points):
        if len(points) != 9 or {p['label'] for p in points} != set(LABELS):
            raise ValueError('Complete all nine calibration positions first')
        self.points = []
        for p in points:
            row = tuple(finite(p[k]) for k in ('camera_x', 'camera_y', 'neck_angle', 'lift_left_angle', 'lift_right_angle'))
            if not all(0 <= v <= 1 for v in row[:2]):
                raise ValueError('Camera coordinates must be normalized')
            self.points.append(row)
        if any(math.dist(a[:2], b[:2]) < .02 for i, a in enumerate(self.points)
               for b in self.points[i+1:]):
            raise ValueError('Calibration positions overlap; spread bottle positions apart')
        # Reject a collapsed workspace (all samples along a line).
        if max(abs((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]))
               for a in self.points for b in self.points for c in self.points) < .01:
            raise ValueError('Calibration must cover a two-dimensional workspace')

    @classmethod
    def load(cls, path, axes):
        data = json.loads(Path(path).read_text())
        if data.get('version') != 2 or data['axes'] != {k: asdict(v) for k, v in axes.items()}:
            raise ValueError('Servo configuration changed; repeat world calibration')
        return cls(data['points'])

    def map(self, x, y):
        x, y = (max(0., min(1., finite(v))) for v in (x, y))
        # Inverse-distance interpolation: exact at samples, continuous, bounded
        # outside the sampled workspace. Uses actual detected coordinates.
        distances = [(x-p[0])**2 + (y-p[1])**2 for p in self.points]
        if min(distances) < 1e-12:
            return self.points[distances.index(min(distances))][2:]
        weights = [1/d for d in distances]
        return tuple(sum(w*p[i] for w, p in zip(weights, self.points))/sum(weights) for i in (2, 3, 4))


class GazeController:
    """Reuse RobotController's transport; pose angles are physical, never inverted twice.

    Call look_at(x,y) every frame; call hold() when detection is lost.
    """
    def __init__(self, robot, axes, calibration=None, clock=time.monotonic):
        self.robot, self.axes, self.calibration, self.clock = robot, axes, calibration, clock
        self.pose = {k: a.center_deg for k, a in axes.items()}
        self.target = None
        self.last = clock()
        self.follow_after = self.last

    def initialize(self):
        from .transport.serial_transport import SerialTransport, wait_for_reply
        link = self.robot.transport
        if isinstance(link, SerialTransport):
            # Opening USB resets an Uno. Wait for this specific firmware first.
            wait_for_reply(link._serial, 'GAZE_READY,2', timeout=6)
        for name, axis in self.axes.items():
            command = f'CONFIG,{name},{axis.pin},{axis.min_deg:.4f},{axis.center_deg:.4f},{axis.max_deg:.4f}'
            link.send_line(command)
            if isinstance(link, SerialTransport):
                wait_for_reply(link._serial, 'CONFIGURED,' + name)
        self.center()

    def set_pose(self, **angles):
        proposed = dict(self.pose)
        for name, value in angles.items():
            axis = self.axes[name]
            proposed[name] = max(axis.min_deg, min(axis.max_deg, finite(value)))
        # Round inward, so even fractional configured limits are respected.
        values = [max(math.ceil(self.axes[k].min_deg*10000)/10000,
                      min(math.floor(self.axes[k].max_deg*10000)/10000, proposed[k])) for k in AXES]
        self.robot.transport.send_line('POSE,' + ','.join(f'{v:.4f}' for v in values))
        self.pose.update(zip(AXES, (float(f'{v:.4f}') for v in values)))
        return dict(self.pose)

    def center(self):
        self.hold()
        return self.set_pose(**{k: a.center_deg for k, a in self.axes.items()})

    def jog(self, axis, delta):
        return self.set_pose(**{axis: self.pose[axis] + delta * (-1 if self.axes[axis].invert else 1)})

    def jog_pair(self, names, delta, differential=False):
        """Preserve paired movement at limits: stop both when either hits its bound."""
        changes = {}
        scale = 1.0
        for index, name in enumerate(names):
            axis = self.axes[name]
            change = finite(delta) * (-1 if axis.invert else 1)
            if differential and index == 1:
                change = -change
            changes[name] = change
            if change:
                room = (axis.max_deg-self.pose[name]) if change > 0 else (self.pose[name]-axis.min_deg)
                scale = min(scale, max(0., room/abs(change)))
        return self.set_pose(**{name: self.pose[name]+change*scale for name, change in changes.items()})

    def hold(self):
        self.target = None
        self.last = self.clock()

    def look_at(self, x, y):
        if self.calibration is None:
            raise ValueError('Load world calibration before tracking')
        point = tuple(max(0., min(1., finite(v))) for v in (x, y))
        now = self.clock()
        dt = min(.1, max(0., now-self.last))
        self.last = now
        if self.target is None or math.dist(point, self.target) > .015:
            # Large changes get a brief eye lead; small detector updates cannot
            # continually postpone the neck's movement.
            if self.target is None or math.dist(point, self.target) > .15:
                self.follow_after = now + .12
            self.target = point
        neck, left, right = self.calibration.map(*self.target)
        neck = max(self.axes['neck'].min_deg, min(self.axes['neck'].max_deg, neck))
        residual = (neck-self.pose['neck']) * (-1 if self.axes['neck'].invert else 1)
        desired = {'neck': neck, 'lift_left': left, 'lift_right': right}
        for name in EYES:
            desired[name] = self.axes[name].center_deg + .7*residual * (-1 if self.axes[name].invert else 1)
        angles = {}
        for name, goal in desired.items():
            axis = self.axes[name]
            goal = max(axis.min_deg, min(axis.max_deg, goal))
            current = self.pose[name]
            if name not in EYES and now < self.follow_after:
                continue
            if abs(goal-current) < .1:
                continue
            smooth = current + (goal-current)*(1-math.exp(-dt/(.06 if name in EYES else .18)))
            angles[name] = step_toward(current, smooth, (100 if name in EYES else 30)*dt)
        return self.set_pose(**angles)
