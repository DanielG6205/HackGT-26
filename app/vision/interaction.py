"""Console-only joint-attention trials using already-smoothed camera gaze scores."""
from enum import Enum, auto
import math
import random

from .models import Gaze

DIRECTIONS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
EYE_CONTACT_PROMPTS = (
    'Can you look at me?',
    'Could you look this way for a moment?',
    'Ready to play? Can you look at me?',
    'Can I have your attention for a moment?',
)
OBJECT_PROMPTS = (
    'Can you look at the {label}?',
    "Let's find the {label}! Can you look over there?",
    'Could you take a look at the {label}?',
    'Now, can you find the {label}?',
)


class InteractionState(Enum):
    WAIT_FOR_EYE_CONTACT = auto()
    SELECT_OBJECT = auto()
    PROMPT_USER = auto()
    WAIT_FOR_GAZE = auto()
    COOLDOWN = auto()


class GazeInteraction:
    """Call update once per fresh frame with monotonic time in seconds.

    Thresholds are heuristic score units, not degrees. N is image up, E is
    image right. None/invalid gaze is UNKNOWN, never CENTER. The tracker already
    smooths head/iris scores; this controller additionally requires a streak.
    """

    def __init__(self, *, horizontal_threshold=0.85, vertical_threshold=0.85,
                 hold_frames=5, timeout=5.0, delay=1.0, emit=print,
                 object_margin=0.1, require_eye_contact=True, max_frame_gap=0.5,
                 allow_center_prompt=False):
        self.allow_center_prompt = allow_center_prompt
        if not math.isfinite(max_frame_gap) or max_frame_gap <= 0:
            raise ValueError('max_frame_gap must be positive')
        self.max_frame_gap = max_frame_gap
        self.initial_state = (InteractionState.WAIT_FOR_EYE_CONTACT if require_eye_contact
                              else InteractionState.SELECT_OBJECT)
        for name, value in (('horizontal_threshold', horizontal_threshold),
                            ('vertical_threshold', vertical_threshold),
                            ('timeout', timeout)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not math.isfinite(delay) or delay < 0:
            raise ValueError('delay must be finite and nonnegative')
        if not isinstance(hold_frames, int) or hold_frames < 1:
            raise ValueError('hold_frames must be a positive integer')
        if not math.isfinite(object_margin) or not 0 < object_margin < 0.5:
            raise ValueError("object_margin must be between 0 and 0.5")
        self.object_margin = object_margin
        self.target_object = None
        self.horizontal_threshold = horizontal_threshold
        self.vertical_threshold = vertical_threshold
        self.hold_frames = hold_frames
        self.timeout = timeout
        self.delay = delay
        self.emit = emit
        self._last_prompts = {}
        self.target_direction = None
        self.direction = 'UNKNOWN'
        self.state = InteractionState.WAIT_FOR_EYE_CONTACT
        self._streak = 0
        self._deadline = None
        self._last_time = None
        self._prompt_pending = False
        self._reported_direction = None
        self._enter(self.initial_state)

    def direction_of(self, gaze: Gaze | None):
        if gaze is None or gaze.looking_at_camera is None:
            return 'UNKNOWN'
        x, y = gaze.horizontal_score, gaze.vertical_score
        if x is None or y is None or not math.isfinite(x) or not math.isfinite(y):
            return 'UNKNOWN'
        horizontal = 'W' if x < -self.horizontal_threshold else 'E' if x > self.horizontal_threshold else ''
        vertical = 'N' if y < -self.vertical_threshold else 'S' if y > self.vertical_threshold else ''
        return vertical + horizontal or 'CENTER'

    def _say_varied(self, kind, options, **values):
        previous = self._last_prompts.get(kind)
        template = random.choice([text for text in options if text != previous])
        self._last_prompts[kind] = template
        self.emit('[ROBOT] ' + template.format(**values))

    def _enter(self, state):
        self.state = state
        self._streak = 0
        self._reported_direction = None
        self.emit(f'[STATE] {state.name}')
        if state is InteractionState.WAIT_FOR_EYE_CONTACT:
            self.target_direction = None
            self._say_varied('eye_contact', EYE_CONTACT_PROMPTS)

    def _finish(self, now):
        self.target_direction = None
        self.target_object = None
        self._deadline = now + self.delay
        self._enter(InteractionState.COOLDOWN)

    def object_direction(self, obj):
        """Coarse image sectors, not a calibrated fixation or 3D gaze test."""
        x, y = obj.center_normalized
        margin = self.object_margin
        horizontal = 'W' if x < 0.5 - margin else 'E' if x > 0.5 + margin else ''
        vertical = 'N' if y < 0.5 - margin else 'S' if y > 0.5 + margin else ''
        return vertical + horizontal or 'CENTER'

    def update(self, gaze: Gaze | None, now: float, objects=(), *, prompt_pending=False):
        if not math.isfinite(now) or (self._last_time is not None and now <= self._last_time):
            raise ValueError('Frame times must be finite and strictly increasing')
        if self._last_time is not None and now - self._last_time > self.max_frame_gap:
            self._streak = 0
        self._last_time = now
        self.direction = self.direction_of(gaze)
        if prompt_pending:
            self._prompt_pending = True
            self._streak = 0
            return
        if self._prompt_pending:
            self._prompt_pending = False
            self._streak = 0
            if self.state is InteractionState.WAIT_FOR_GAZE:
                self._deadline = now + self.timeout
            elif self.state is InteractionState.COOLDOWN:
                self._deadline = now + self.delay
            return  # Start counting on a fresh frame after playback completes.
        if self.state is InteractionState.COOLDOWN:
            if now >= self._deadline:
                self._enter(self.initial_state)
            return
        if self.direction != self._reported_direction:
            self.emit(f'[GAZE] {self.direction}')
            self._reported_direction = self.direction
        if self.state is InteractionState.WAIT_FOR_EYE_CONTACT:
            self._streak = self._streak + 1 if self.direction == 'CENTER' else 0
            if self._streak < self.hold_frames:
                return
            self.emit('[SUCCESS] User made eye contact.')
            self._enter(InteractionState.SELECT_OBJECT)
            self.emit('[INFO] Waiting for a tracked non-person object outside CENTER.')
        if self.state is InteractionState.SELECT_OBJECT:
            # Center objects cannot be distinguished from continued eye contact.
            candidates = [o for o in objects if o.track_id is not None
                          and o.label != 'person' and
                          (self.allow_center_prompt or self.object_direction(o) != 'CENTER')]
            if not candidates:
                return
            self.target_object = max(candidates, key=lambda o: o.confidence)
            self.target_direction = self.object_direction(self.target_object)
            self._enter(InteractionState.PROMPT_USER)
            self._say_varied('object', OBJECT_PROMPTS, label=self.target_object.label)
            self.emit(f'[TARGET] {self.target_object.label} #{self.target_object.track_id} '
                      f'{self.target_direction}')
            self._deadline = now + self.timeout
            self._enter(InteractionState.WAIT_FOR_GAZE)
            return
        if self.state is InteractionState.WAIT_FOR_GAZE:
            target = self.target_object
            if now >= self._deadline:
                self.emit(f'[TIMEOUT] User did not follow {target.label} #{target.track_id}.')
                self._finish(now)
                return
            current = next((o for o in objects if o.track_id == target.track_id
                            and o.label == target.label), None)
            direction = self.object_direction(current) if current else None
            if direction != self.target_direction:
                self._streak = 0
                self.target_direction = direction
                self.emit(f'[TARGET] {target.label} #{target.track_id} {direction or "LOST"}')
            # A lost target cannot succeed, nor can one that moves into CENTER.
            matches = direction in DIRECTIONS and self.direction == direction
            self._streak = self._streak + 1 if matches else 0
            if self._streak >= self.hold_frames:
                self.emit(f'[SUCCESS] User followed gaze toward {target.label} #{target.track_id}.')
                self.emit('[ROBOT] Hurray!')
                self._finish(now)
