"""Console-only joint-attention trials using already-smoothed camera gaze scores."""
from enum import Enum, auto
import math
import random

from .models import Gaze

DIRECTIONS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')


class InteractionState(Enum):
    LOOK_AT_ROBOT = auto()
    WAIT_FOR_GAZE_FOLLOW = auto()
    COOLDOWN = auto()


class GazeInteraction:
    """Call update once per fresh frame with monotonic time in seconds.

    Thresholds are heuristic score units, not degrees. N is image up, E is
    image right. None/invalid gaze is UNKNOWN, never CENTER. The tracker already
    smooths head/iris scores; this controller additionally requires a streak.
    """

    def __init__(self, *, horizontal_threshold=0.65, vertical_threshold=0.65,
                 hold_frames=5, timeout=5.0, delay=1.0, emit=print,
                 choose_target=None):
        for name, value in (('horizontal_threshold', horizontal_threshold),
                            ('vertical_threshold', vertical_threshold),
                            ('timeout', timeout)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not math.isfinite(delay) or delay < 0:
            raise ValueError('delay must be finite and nonnegative')
        if not isinstance(hold_frames, int) or hold_frames < 1:
            raise ValueError('hold_frames must be a positive integer')
        self.horizontal_threshold = horizontal_threshold
        self.vertical_threshold = vertical_threshold
        self.hold_frames = hold_frames
        self.timeout = timeout
        self.delay = delay
        self.emit = emit
        # Replace this callback later with direction_of_detected_object.
        self.choose_target = choose_target or (lambda: random.choice(DIRECTIONS))
        self.target_direction = None
        self.direction = 'UNKNOWN'
        self.state = InteractionState.LOOK_AT_ROBOT
        self._streak = 0
        self._deadline = None
        self._last_time = None
        self._reported_direction = None
        self._enter(InteractionState.LOOK_AT_ROBOT)

    def direction_of(self, gaze: Gaze | None):
        if gaze is None or gaze.looking_at_camera is None:
            return 'UNKNOWN'
        x, y = gaze.horizontal_score, gaze.vertical_score
        if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
            return 'UNKNOWN'
        horizontal = 'W' if x < -self.horizontal_threshold else 'E' if x > self.horizontal_threshold else ''
        vertical = 'N' if y < -self.vertical_threshold else 'S' if y > self.vertical_threshold else ''
        return vertical + horizontal or 'CENTER'

    def _enter(self, state):
        self.state = state
        self._streak = 0
        self._reported_direction = None
        self.emit(f'[STATE] {state.name}')
        if state is InteractionState.LOOK_AT_ROBOT:
            self.target_direction = None
            self.emit('[ROBOT] Look at me!')

    def _finish(self, now):
        self.target_direction = None
        self._deadline = now + self.delay
        self._enter(InteractionState.COOLDOWN)

    def update(self, gaze: Gaze | None, now: float):
        if not math.isfinite(now) or (self._last_time is not None and now <= self._last_time):
            raise ValueError('Frame times must be finite and strictly increasing')
        if self._last_time is not None and now - self._last_time > 0.5:
            self._streak = 0  # Paused capture cannot complete a consecutive streak.
        self._last_time = now
        self.direction = self.direction_of(gaze)
        if self.state is InteractionState.COOLDOWN:
            if now >= self._deadline:
                self._enter(InteractionState.LOOK_AT_ROBOT)
            return  # Count only frames captured after the new prompt.
        if self.direction != self._reported_direction:
            self.emit(f'[GAZE] {self.direction}')
            self._reported_direction = self.direction
        if self.state is InteractionState.WAIT_FOR_GAZE_FOLLOW and now >= self._deadline:
            self.emit('[TIMEOUT] User did not follow target.')
            self._finish(now)
            return
        expected = 'CENTER' if self.state is InteractionState.LOOK_AT_ROBOT else self.target_direction
        self._streak = self._streak + 1 if self.direction == expected else 0
        if self._streak < self.hold_frames:
            return
        if self.state is InteractionState.LOOK_AT_ROBOT:
            target = self.choose_target()
            if target not in DIRECTIONS:
                raise ValueError('Target must be one of N, NE, E, SE, S, SW, W, NW')
            self.emit('[SUCCESS] User made eye contact.')
            self.target_direction = target
            self._deadline = now + self.timeout
            self._enter(InteractionState.WAIT_FOR_GAZE_FOLLOW)
            self.emit('[ROBOT] Hey, look over there!')
            self.emit(f'[TARGET] {target}')
        else:
            self.emit(f'[SUCCESS] User followed gaze toward {self.target_direction}.')
            self._finish(now)
