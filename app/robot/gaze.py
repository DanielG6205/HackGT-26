"""Five-servo physical-angle calibration and deterministic gaze motion."""

import json
import math
import time
from dataclasses import asdict
from pathlib import Path
    
from .config import ServoAxisConfig
from .mapping import step_toward
from .controller import LookState


AXES = (
    "eye_left",
    "eye_right",
    "neck",
    "lift_left",
    "lift_right",
)

EYES = (
    "eye_left",
    "eye_right",
)

LIFTS = (
    "lift_left",
    "lift_right",
)

LABELS = ("center", "top", "bottom", "left", "right")

LEGACY_LABELS = (
    "top-left",
    "top-center",
    "top-right",
    "middle-left",
    "center",
    "middle-right",
    "bottom-left",
    "bottom-center",
    "bottom-right",
)


def finite(value):
    """Convert a value to float and reject NaN/infinity."""
    value = float(value)

    if not math.isfinite(value):
        raise ValueError("Angles and coordinates must be finite")

    return value


def load_axes(path):
    """
    Load and validate the five physical gaze servos.

    The five axes are:
        eye_left
        eye_right
        neck
        lift_left
        lift_right

    Pins 6 and 7 are reserved for eyelids.
    """

    data = json.loads(Path(path).read_text())

    if set(data) - {"mouth"} != set(AXES):
        raise ValueError(
            "Expected five servos: "
            + ", ".join(AXES)
            + "; update the old three-axis config"
        )

    axes = {
        name: ServoAxisConfig(**data[name])
        for name in AXES
    }

    pins = [axis.pin for axis in axes.values()]
    if "mouth" in data and data["mouth"]["pin"] in pins:
        raise ValueError("Mouth pin must be separate from all gaze servos")

    if (
        len(set(pins)) != len(AXES)
        or any(pin not in range(2, 14) for pin in pins)
    ):
        raise ValueError(
            "Use five distinct Uno digital pins 2..13"
        )

    if any(pin in (6, 7) for pin in pins):
        raise ValueError(
            "Pins 6 and 7 are reserved for Arduino-controlled eyelids"
        )

    if any(
        not axis.enabled
        or not 0 <= axis.min_deg <= axis.max_deg <= 180
        for axis in axes.values()
    ):
        raise ValueError(
            "All five servos must be enabled with limits within 0..180"
        )

    if any(
        math.ceil(axis.min_deg * 10000)
        > math.floor(axis.max_deg * 10000)
        for axis in axes.values()
    ):
        raise ValueError(
            "Servo limits must allow a representable four-decimal angle"
        )

    return axes


def save_points(path, axes, points):
    """
    Atomically save calibration progress.

    This intentionally saves incomplete calibration sessions too,
    so a calibration run can be resumed/recovered.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary = path.with_suffix(path.suffix + ".tmp")

    temporary.write_text(
        json.dumps(
            {
                "version": 2,
                "axes": {
                    name: asdict(axis)
                    for name, axis in axes.items()
                },
                "points": points,
            },
            indent=2,
        )
        + "\n"
    )

    temporary.replace(path)


class GazeMap:
    """
    Map normalized camera/world coordinates to physical servo angles.

    New calibration uses center, top, bottom, left, right.
    Existing nine-point files remain supported:

        top-left       top-center       top-right
        middle-left   center           middle-right
        bottom-left   bottom-center   bottom-right

    Each point contains:

        camera_x
        camera_y
        neck_angle
        lift_left_angle
        lift_right_angle
    """

    def __init__(self, points):
        if not any(
            len(points) == len(labels)
            and {point["label"] for point in points} == set(labels)
            for labels in (LABELS, LEGACY_LABELS)
        ):
            raise ValueError(
                "Complete center, top, bottom, left, and right (or load a complete legacy nine-point file)"
            )

        self.labels = [point["label"] for point in points]
        self.points = []

        for point in points:
            row = tuple(
                finite(point[key])
                for key in (
                    "camera_x",
                    "camera_y",
                    "neck_angle",
                    "lift_left_angle",
                    "lift_right_angle",
                )
            )

            if not all(0 <= value <= 1 for value in row[:2]):
                raise ValueError(
                    "Camera coordinates must be normalized"
                )

            self.points.append(row)

        # Calibration points must not overlap.
        if any(
            math.dist(a[:2], b[:2]) < 0.02
            for i, a in enumerate(self.points)
            for b in self.points[i + 1 :]
        ):
            raise ValueError(
                "Calibration positions overlap; "
                "spread bottle positions apart"
            )

        # Reject a collapsed workspace where all samples
        # effectively lie along a line.
        if (
            max(
                abs(
                    (b[0] - a[0]) * (c[1] - a[1])
                    - (b[1] - a[1]) * (c[0] - a[0])
                )
                for a in self.points
                for b in self.points
                for c in self.points
            )
            < 0.01
        ):
            raise ValueError(
                "Calibration must cover a two-dimensional workspace"
            )

    @classmethod
    def load(cls, path, axes):
        """Load a completed calibration and verify its servo configuration."""

        data = json.loads(Path(path).read_text())

        expected_axes = {
            name: asdict(axis)
            for name, axis in axes.items()
        }

        if (
            data.get("version") != 2
            or data["axes"] != expected_axes
        ):
            raise ValueError(
                "Servo configuration changed; "
                "repeat world calibration"
            )

        return cls(data["points"])

    def map(self, x, y):
        """
        Convert normalized camera coordinates into:

            neck angle
            left lift angle
            right lift angle

        using inverse-distance interpolation between the
        measured calibration points.
        """

        x, y = (
            max(0.0, min(1.0, finite(value)))
            for value in (x, y)
        )

        distances = [
            (x - point[0]) ** 2 + (y - point[1]) ** 2
            for point in self.points
        ]

        # Exact calibration point.
        if min(distances) < 1e-12:
            return self.points[
                distances.index(min(distances))
            ][2:]

        if len(self.points) == 5:
            # A five-point session is a fan around the measured center. Linear
            # triangles preserve direction instead of IDW pulling distant targets
            # back toward the average servo pose. Outside: nearest calibrated edge.
            center = self.points[self.labels.index("center")]
            outer = sorted((p for p in self.points if p is not center),
                           key=lambda p: math.atan2(p[1]-center[1], p[0]-center[0]))
            nearest = None
            for i, a in enumerate(outer):
                b = outer[(i+1) % len(outer)]
                denominator = (a[1]-b[1])*(center[0]-b[0]) + (b[0]-a[0])*(center[1]-b[1])
                if abs(denominator) < 1e-10:
                    continue
                wc = ((a[1]-b[1])*(x-b[0]) + (b[0]-a[0])*(y-b[1])) / denominator
                wa = ((b[1]-center[1])*(x-b[0]) + (center[0]-b[0])*(y-b[1])) / denominator
                wb = 1-wc-wa
                if min(wc, wa, wb) >= -1e-9:
                    weights = [max(0., w) for w in (wc, wa, wb)]
                    return tuple(sum(w*p[j] for w,p in zip(weights,(center,a,b)))/sum(weights)
                                 for j in (2,3,4))
                dx, dy = b[0]-a[0], b[1]-a[1]
                t = max(0., min(1., ((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
                distance = (x-a[0]-t*dx)**2 + (y-a[1]-t*dy)**2
                if nearest is None or distance < nearest[0]:
                    nearest = (distance, tuple(a[j]+t*(b[j]-a[j]) for j in (2,3,4)))
            if nearest is not None:
                return nearest[1]

        # Inverse-distance weighting.
        weights = [1 / distance for distance in distances]

        return tuple(
            sum(
                weight * point[index]
                for weight, point in zip(weights, self.points)
            )
            / sum(weights)
            for index in (2, 3, 4)
        )


class GazeController:
    """
    Five-servo calibrated gaze controller.

    Public interface used by the rest of the application:

        look_at(x, y)
        hold()
        center()
        state
        center_eyes()
        close()

    The application deals only in normalized coordinates.

    This class converts those coordinates into physical servo
    angles and sends:

        POSE,eye_left,eye_right,neck,lift_left,lift_right

    to the Arduino.
    """

    def __init__(
        self,
        robot,
        axes,
        calibration=None,
        clock=time.monotonic,
    ):
        self.robot = robot
        self.axes = axes
        self.calibration = calibration
        self.clock = clock

        # Current physical servo pose.
        self.pose = {
            name: axis.center_deg
            for name, axis in axes.items()
        }

        # Current normalized target.
        self.target = None

        self.last = clock()
        self.follow_after = self.last

    def initialize(self):
        """
        Initialize the Arduino-side gaze configuration.

        For USB serial, the Arduino resets when the serial
        connection opens, so wait for:

            GAZE_READY,2

        Then configure all five axes.
        """

        from .transport.serial_transport import (
            SerialTransport,
            wait_for_reply,
        )

        link = self.robot.transport
        from .transport.mock import MockTransport
        if not isinstance(link, (SerialTransport, MockTransport)):
            raise ValueError("Calibrated gaze requires --transport serial (or mock), not Bluetooth/Wi-Fi")

        if isinstance(link, SerialTransport):
            wait_for_reply(
                link._serial,
                "GAZE_READY,2",
                timeout=6,
            )

        for name, axis in self.axes.items():
            command = (
                f"CONFIG,"
                f"{name},"
                f"{axis.pin},"
                f"{axis.min_deg:.4f},"
                f"{axis.center_deg:.4f},"
                f"{axis.max_deg:.4f}"
            )

            link.send_line(command)

            if isinstance(link, SerialTransport):
                wait_for_reply(
                    link._serial,
                    "CONFIGURED," + name,
                )

        # Put all five servos at their calibrated centers.
        self.center()

    def set_pose(self, **angles):
        """
        Set physical servo angles.

        Values are clamped to configured limits before being
        transmitted to the Arduino.
        """

        proposed = dict(self.pose)

        for name, value in angles.items():
            if name not in self.axes:
                raise KeyError(
                    f"Unknown gaze axis: {name}"
                )

            axis = self.axes[name]

            proposed[name] = max(
                axis.min_deg,
                min(
                    axis.max_deg,
                    finite(value),
                ),
            )

        # Round inward so fractional configured limits remain valid.
        values = [
            max(
                math.ceil(self.axes[name].min_deg * 10000)
                / 10000,
                min(
                    math.floor(self.axes[name].max_deg * 10000)
                    / 10000,
                    proposed[name],
                ),
            )
            for name in AXES
        ]

        command = (
            "POSE,"
            + ",".join(
                f"{value:.4f}"
                for value in values
            )
        )

        self.robot.transport.send_line(command)

        self.pose.update(
            zip(
                AXES,
                (
                    float(f"{value:.4f}")
                    for value in values
                ),
            )
        )

        return dict(self.pose)

    def center(self):
        """Stop tracking and move all five gaze servos to center."""

        self.hold()

        return self.set_pose(
            **{
                name: axis.center_deg
                for name, axis in self.axes.items()
            }
        )

    def jog(self, axis, delta):
        """Manually move one axis by delta degrees."""

        if axis not in self.axes:
            raise KeyError(
                f"Unknown gaze axis: {axis}"
            )

        direction = (
            -1
            if self.axes[axis].invert
            else 1
        )

        return self.set_pose(
            **{
                axis:
                    self.pose[axis]
                    + delta * direction
            }
        )

    def jog_pair(
        self,
        names,
        delta,
        differential=False,
    ):
        """
        Move a pair of axes while preserving synchronized
        movement when either axis reaches its limit.
        """

        changes = {}
        scale = 1.0

        for index, name in enumerate(names):
            if name not in self.axes:
                raise KeyError(
                    f"Unknown gaze axis: {name}"
                )

            axis = self.axes[name]

            change = (
                finite(delta)
                * (
                    -1
                    if axis.invert
                    else 1
                )
            )

            if differential and index == 1:
                change = -change

            changes[name] = change

            if change:
                room = (
                    axis.max_deg - self.pose[name]
                    if change > 0
                    else self.pose[name] - axis.min_deg
                )

                scale = min(
                    scale,
                    max(
                        0.0,
                        room / abs(change),
                    ),
                )

        return self.set_pose(
            **{
                name:
                    self.pose[name]
                    + change * scale
                for name, change in changes.items()
            }
        )

    def hold(self):
        """
        Stop following the current target.

        The servos themselves remain at their current physical
        positions.
        """

        self.target = None
        self.last = self.clock()

    def look_at(self, x, y):
        """
        Track a normalized target.

        x and y are normalized camera/world coordinates:

            x = 0.0 -> left
            x = 1.0 -> right
            y = 0.0 -> top
            y = 1.0 -> bottom
        """

        if self.calibration is None:
            raise ValueError(
                "Load world calibration before tracking"
            )

        point = tuple(
            max(0.0, min(1.0, finite(value)))
            for value in (x, y)
        )

        now = self.clock()

        dt = min(
            0.1,
            max(
                0.0,
                now - self.last,
            ),
        )

        self.last = now

        if (
            self.target is None
            or math.dist(point, self.target) > 0.015
        ):
            # Large target changes give the eyes a brief lead
            # before the head/lifts follow.
            if (
                self.target is None
                or math.dist(point, self.target) > 0.15
            ):
                self.follow_after = now + 0.12

            self.target = point

        neck, left, right = self.calibration.map(
            *self.target
        )

        # Clamp the calibrated neck angle.
        neck = max(
            self.axes["neck"].min_deg,
            min(
                self.axes["neck"].max_deg,
                neck,
            ),
        )

        residual = (
            neck - self.pose["neck"]
        ) * (
            -1
            if self.axes["neck"].invert
            else 1
        )

        desired = {
            "neck": neck,
            "lift_left": left,
            "lift_right": right,
        }

        # Eyes lead the head slightly.
        for name in EYES:
            desired[name] = (
                self.axes[name].center_deg
                + 0.7
                * residual
                * (
                    -1
                    if self.axes[name].invert
                    else 1
                )
            )

        angles = {}

        for name, goal in desired.items():
            axis = self.axes[name]

            goal = max(
                axis.min_deg,
                min(
                    axis.max_deg,
                    goal,
                ),
            )

            current = self.pose[name]

            # During the brief eye-lead period, let the eyes move
            # first while the neck/lifts wait.
            if (
                name not in EYES
                and now < self.follow_after
            ):
                continue

            if abs(goal - current) < 0.1:
                continue

            # Exponential smoothing.
            smooth = current + (
                goal - current
            ) * (
                1
                - math.exp(
                    -dt
                    / (
                        0.06
                        if name in EYES
                        else 0.18
                    )
                )
            )

            angles[name] = step_toward(
                current,
                smooth,
                (
                    100
                    if name in EYES
                    else 30
                ) * dt,
            )

        return self.set_pose(**angles)

    @property
    def state(self):
        """
        Compatibility state for app.main.

        app.main previously expected RobotController.state.
        GazeController therefore exposes the same basic state
        shape while the real physical state remains self.pose.
        """

        x, y = (
            self.target
            if self.target is not None
            else (0.5, 0.5)
        )

        return LookState(
            x=x,
            y=y,
            eye_x_deg=(
                self.pose["eye_left"]
                + self.pose["eye_right"]
            ) / 2.0,
            eye_y_deg=0.0,
            head_x_deg=self.pose["neck"],
            head_y_deg=(
                self.pose["lift_left"]
                + self.pose["lift_right"]
            ) / 2.0,
            expression="neutral",
        )

    def center_eyes(self):
        """
        Compatibility alias used by app.main.

        The calibrated gaze system has five coordinated axes,
        so centering the eyes means centering the entire gaze pose.
        """

        return self.center()

    def close(self):
        """
        Compatibility method used by app.main.

        The underlying RobotController owns the transport.
        """

        self.robot.close()

