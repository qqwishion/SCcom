import math
from dataclasses import dataclass

from skillcheck_detector import Observation, Target, difference


@dataclass(frozen=True)
class Decision:
    fire: bool = False
    eta_ms: float | None = None
    new_target: bool = False


class TimingPredictor:
    """Latch one shot per confirmed target, including endless checks.

    Rearm on a stable new target, not on needle motion or a single missed frame.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.target: Target | None = None
        self.candidate: Target | None = None
        self.candidate_count = 0
        self.fired = False

    @staticmethod
    def same(a: Target, b: Target) -> bool:
        return abs(difference(a.angle, b.angle)) < math.radians(5) and abs(
            a.width - b.width
        ) < math.radians(7)

    def update(self, observation: Observation, speed: float | None, lead_s: float) -> Decision:
        target, angle = observation.target, observation.pointer
        if target is None:
            self.candidate = None
            self.candidate_count = 0
            # Near the crossing the needle may cover the entire solid white patch.
            if (
                self.target is None
                or angle is None
                or abs(difference(angle, self.target.angle)) > self.target.width + 0.10
            ):
                return Decision()
            target = self.target
        new = False
        if self.target is None or not self.same(target, self.target):
            if self.candidate is not None and self.same(target, self.candidate):
                self.candidate_count += 1
            else:
                self.candidate, self.candidate_count = target, 1
            if self.candidate_count < 2:
                return Decision()
            self.target, self.fired, new = target, False, True
            self.candidate = None
            self.candidate_count = 0
        else:
            self.candidate = None
            self.candidate_count = 0
        # The red needle partially covers the white target at the exact crossing.
        # Preserve its last confirmed full geometry rather than chasing the visible fragment.
        target = self.target
        if angle is None or speed is None or self.fired:
            return Decision(new_target=new)
        # Require a visible overlap of the white segment and the red shaft on the
        # track. Checking only the needle's center discards valid edge crossings.
        half = target.overlap_half_width(observation.pointer_width)
        observed_error = difference(target.angle, angle)
        projected = angle + speed * lead_s
        error = difference(target.angle, projected)
        eta = error / speed
        inside = abs(error) <= half
        fire = abs(observed_error) <= half and inside
        return Decision(fire, eta * 1000, new)

    def mark_fired(self) -> None:
        self.fired = True
