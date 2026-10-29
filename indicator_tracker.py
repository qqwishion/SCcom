import math
from collections import deque
from statistics import median

from skillcheck_detector import difference


class IndicatorTracker:
    def __init__(self):
        self.samples: deque[tuple[float, float]] = deque(maxlen=24)
        self.speed: float | None = None
        self.sample_time: float | None = None

    def reset(self) -> None:
        self.samples.clear()
        self.speed = None
        self.sample_time = None

    def update(self, angle: float, timestamp: float) -> float | None:
        if self.samples:
            last_t, last_angle = self.samples[-1]
            dt = timestamp - last_t
            delta = difference(angle, last_angle)
            if dt <= 0:
                return None
            if dt > 0.15 or abs(delta) > max(0.6, dt * 60):
                self.reset()
            elif abs(delta) < math.radians(0.4):
                # Repeated desktop frames are not evidence that the needle slowed down.
                # Keep the timestamp of the image that actually advanced the needle.
                return self.speed if dt < 0.08 else None
            elif delta < -math.radians(4):
                self.reset()
            else:
                angle = last_angle + delta
        self.samples.append((timestamp, angle))
        self.sample_time = timestamp
        while len(self.samples) > 3 and timestamp - self.samples[0][0] > 0.14:
            self.samples.popleft()
        if len(self.samples) < 3:
            return None
        samples = list(self.samples)
        slopes = [
            (b - a) / (tb - ta)
            for i, (ta, a) in enumerate(samples)
            for tb, b in samples[i + 1 :]
            if tb - ta >= 0.025
        ]
        if not slopes:
            return None
        speed = median(slopes)
        intercept = median(a - speed * (t - timestamp) for t, a in samples)
        residual = median(abs(a - (intercept + speed * (t - timestamp))) for t, a in samples)
        self.speed = (
            speed if 0.2 < speed < 60 and residual < max(math.radians(4), speed * 0.018) else None
        )
        return self.speed
