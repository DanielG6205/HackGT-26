"""Camera-to-robot normalized coordinates; firmware owns physical travel limits."""
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class LookMapping:
    x_gain: float = 1.0
    y_gain: float = 1.0
    x_offset: float = 0.0
    y_offset: float = 0.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Eye mapping values must be finite')
        if not all(0 < abs(v) <= 2 for v in (self.x_gain, self.y_gain)):
            raise ValueError('Eye mapping gain magnitude must be > 0 and <= 2')
        if max(abs(self.x_offset), abs(self.y_offset)) > .25:
            raise ValueError('Eye mapping offsets must be within -0.25..0.25')

    def apply(self, x, y):
        return tuple(max(0., min(1., .5 + (v - .5) * gain + offset))
                     for v, gain, offset in ((x, self.x_gain, self.x_offset),
                                              (y, self.y_gain, self.y_offset)))

    @classmethod
    def load(cls, path=None):
        return cls(**json.loads(Path(path).read_text())) if path else cls()
