import math
from dataclasses import dataclass

from skillcheck_detector import Observation, Target, difference


@dataclass(frozen=True)
class Decision:
    fire: bool = False
    eta_ms: float | None = None
    new_target: bool = False
    zone: str | None = None


class TimingPredictor:
    """Latch one shot per confirmed target, including endless checks.

    Rearm on a stable new target, not on needle motion or a single missed frame.
    """

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.target: Target | None = None
        self.target_id: object | None = None
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
                or (
                    abs(difference(angle, self.target.angle)) > self.target.width + 0.10
                    and (
                        self.target.gray_region() is None
                        or abs(difference(angle, self.target.gray_angle))
                        > self.target.gray_width / 2 + 0.10
                    )
                )
            ):
                return Decision()
            target = self.target
        # A red shaft can leave only a narrow fragment of the same white patch.
        # Such a contained fragment must not rearm input or restart confirmation.
        if (
            self.target is not None
            and target.width < self.target.width
            and abs(difference(target.angle, self.target.angle)) + target.width / 2
            <= self.target.width / 2 + math.radians(1.5)
        ):
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
            self.target_id = object()
            self.candidate = None
            self.candidate_count = 0
        else:
            self.candidate = None
            self.candidate_count = 0
            if self.target.gray_angle is None and target.gray_angle is not None:
                self.target = Target(
                    self.target.angle, self.target.width, target.gray_angle, target.gray_width
                )
        # The red needle partially covers the white target at the exact crossing.
        # Preserve its last confirmed full geometry rather than chasing the visible fragment.
        target = self.target
        if angle is None or speed is None or self.fired:
            return Decision(new_target=new)
        # Require a visible overlap of the white segment and the red shaft on the
        # track. Checking only the needle's center discards valid edge crossings.
        for zone, region in (("white", target), ("gray", target.gray_region())):
            if region is None:
                continue
            if (
                zone == "gray"
                and not target.width / 2 <= (angle - target.angle) % (2 * math.pi) <= math.pi
            ):
                continue
            half = region.overlap_half_width(observation.pointer_width)
            observed_error = difference(region.angle, angle)
            projected = angle + speed * lead_s
            error = difference(region.angle, projected)
            if abs(observed_error) <= half and abs(error) <= half:
                return Decision(True, error / speed * 1000, new, zone)
        return Decision(new_target=new)

    def mark_fired(self) -> None:
        self.fired = True
