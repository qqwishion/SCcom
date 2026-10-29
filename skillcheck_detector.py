"""Geometric detection only: BGR image in, circle/target/pointer out.

Angles start at 12 o'clock and increase clockwise, in radians.
"""

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TAU = 2 * math.pi


def difference(a: float, b: float) -> float:
    return (a - b + math.pi) % TAU - math.pi


@dataclass(frozen=True)
class Target:
    angle: float
    width: float
    gray_angle: float | None = None
    gray_width: float = 0.0

    def gray_region(self) -> "Target | None":
        if self.gray_angle is None or self.gray_width <= 0:
            return None
        return Target(self.gray_angle, self.gray_width)

    def overlap_half_width(self, pointer_width: float) -> float:
        margin = min(math.radians(0.3), self.width * 0.1)
        return max(0.0, (self.width + pointer_width) / 2 - margin)


@dataclass(frozen=True)
class Observation:
    center: tuple[float, float]
    radius: float
    target: Target | None
    pointer: float | None
    pointer_width: float = 0.0


def runs(mask: np.ndarray) -> list[np.ndarray]:
    """Contiguous true runs, joining the 0/360-degree boundary."""
    indexes = np.flatnonzero(mask)
    if not len(indexes):
        return []
    groups = list(np.split(indexes, np.flatnonzero(np.diff(indexes) > 1) + 1))
    if len(groups) > 1 and mask[0] and mask[-1]:
        groups = [np.concatenate((groups[-1], groups[0]))] + groups[1:-1]
    return groups


class SkillcheckDetector:
    def __init__(self, min_radius: int = 35, max_radius: int = 130):
        self.min_radius = min_radius
        self.max_radius = max_radius
        self.circle: tuple[float, float, float] | None = None
        self.angles = np.arange(720, dtype=np.float32) * (TAU / 720)
        self.sin = np.sin(self.angles)
        self.cos = np.cos(self.angles)
        self.maps: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
        self.icon_template = cv2.imread(
            str(Path(__file__).parent / "assets" / "space_template.png"), cv2.IMREAD_GRAYSCALE
        )
        if self.icon_template is None:
            raise RuntimeError("Missing assets/space_template.png")

    def reset(self) -> None:
        self.circle = None
        self.maps.clear()

    def polar(
        self, mask: np.ndarray, circle: tuple, lo: float, hi: float, samples: int
    ) -> np.ndarray:
        key = (*circle, lo, hi, samples)
        if key not in self.maps:
            x, y, radius = circle
            radii = np.linspace(lo * radius, hi * radius, samples, dtype=np.float32)[:, None]
            self.maps[key] = (x + radii * self.sin, y - radii * self.cos)
        mx, my = self.maps[key]
        return (
            cv2.remap(mask, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT).astype(
                np.float32
            )
            / 255
        )

    def ring_score(self, white: np.ndarray, circle: tuple) -> float:
        return float(self.polar(white, circle, 0.97, 1.03, 7).max(axis=0).mean())

    def icon_score(self, white: np.ndarray, circle: tuple) -> float:
        x, y, r = circle
        patch = cv2.getRectSubPix(white, (max(1, int(r * 1.3)), max(1, int(r * 0.8))), (x, y))
        patch = cv2.resize(patch, (86, 54), interpolation=cv2.INTER_NEAREST)
        return float(cv2.matchTemplate(patch, self.icon_template, cv2.TM_CCOEFF_NORMED).max())

    def refine(self, white: np.ndarray, circle: tuple) -> tuple:
        x, y, radius = circle
        for _ in range(2):
            radii = np.linspace(radius - 6, radius + 6, 25, dtype=np.float32)[:, None]
            mx = x + radii * self.sin[::2]
            my = y - radii * self.cos[::2]
            sampled = (
                cv2.remap(white, mx.astype(np.float32), my.astype(np.float32), cv2.INTER_NEAREST)
                > 0
            )
            count = sampled.sum(axis=0)
            valid = (count >= 1) & (count <= 10)
            if valid.sum() < 150:
                break
            distances = (sampled * radii).sum(axis=0) / np.maximum(count, 1)
            px = x + distances[valid] * self.sin[::2][valid]
            py = y - distances[valid] * self.cos[::2][valid]
            # Center coordinates improve conditioning of the least-squares fit.
            dx, dy = px - x, py - y
            a, b, c = np.linalg.lstsq(
                np.column_stack((2 * dx, 2 * dy, np.ones(len(dx)))), dx * dx + dy * dy, rcond=None
            )[0]
            x, y, radius = x + a, y + b, math.sqrt(max(1, c + a * a + b * b))
        return float(x), float(y), float(radius)

    def find_circle(self, white: np.ndarray, gray: np.ndarray) -> tuple | None:
        # White geometry suppresses most scenery and avoids relying on fixed coordinates.
        small = cv2.resize(gray, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        found = cv2.HoughCircles(
            small,
            cv2.HOUGH_GRADIENT,
            1,
            18,
            param1=80,
            param2=20,
            minRadius=max(5, self.min_radius // 2),
            maxRadius=self.max_radius // 2,
        )
        if found is None:
            return None
        best, score = None, 0.72
        for raw in found[0] * 2:
            raw_circle = tuple(float(v) for v in raw)
            if self.icon_score(white, raw_circle) < 0.25:
                continue
            if self.ring_score(white, raw_circle) < 0.35:
                continue
            candidate = self.refine(white, raw_circle)
            quality = self.ring_score(white, candidate)
            # Match the actual central ornament, not just arbitrary white scenery.
            if quality > score and self.icon_score(white, candidate) > 0.38:
                best, score = candidate, quality
        self.maps.clear()
        return best

    def following_gray(
        self, white: np.ndarray, circle: tuple, white_group: np.ndarray
    ) -> tuple[float | None, float]:
        band = self.polar(white, circle, 0.90, 1.10, 33)
        # The gray sector has two bright radial rims and a dark interior.
        outlined = (
            (band[:10].max(axis=0) > 0.5)
            & (band[23:].max(axis=0) > 0.5)
            & (band[12:22].mean(axis=0) < 0.55)
        )
        start = (int(white_group[-1]) + 1) % len(self.angles)
        support = [bool(outlined[(start + i) % len(self.angles)]) for i in range(180)]
        # Close only short raster gaps; never infer a sector from an unbounded ring.
        first = next((i for i in range(4) if support[i]), None)
        if first is None:
            return None, 0.0
        last, gap = first, 0
        for i in range(first, len(support)):
            if support[i]:
                last, gap = i, 0
            else:
                gap += 1
                if gap >= 4:
                    break
        if last - first + 1 < 6 or last >= len(support) - 4:
            return None, 0.0
        indexes = (start + np.arange(first, last + 1)) % len(self.angles)
        angle = math.atan2(float(self.sin[indexes].mean()), float(self.cos[indexes].mean())) % TAU
        return angle, len(indexes) * TAU / len(self.angles)

    def detect(self, frame: np.ndarray) -> Observation | None:
        b, g, r = cv2.split(frame[:, :, :3])
        low = cv2.min(cv2.min(b, g), r)
        high = cv2.max(cv2.max(b, g), r)
        white = np.where((low >= 140) & ((high.astype(np.int16) - low) < 65), 255, 0).astype(
            np.uint8
        )
        red = np.where(
            (r > 105) & (r.astype(np.float32) > g * 1.65) & (r.astype(np.float32) > b * 1.45),
            255,
            0,
        ).astype(np.uint8)
        if self.circle is not None and (
            self.ring_score(white, self.circle) < 0.62 or self.icon_score(white, self.circle) < 0.30
        ):
            self.reset()
        if self.circle is None:
            self.circle = self.find_circle(white, cv2.cvtColor(frame[:, :, :3], cv2.COLOR_BGR2GRAY))
        if self.circle is None:
            return None
        circle = self.circle
        # Thick white target extends much farther radially than the thin track.
        thick = self.polar(white, circle, 0.925, 1.075, 17).mean(axis=0)
        groups = runs(thick > 0.57)
        candidates = [g for g in groups if 3 <= len(g) <= 170]
        target = None
        if candidates:
            group = max(candidates, key=lambda g: float(thick[g].sum()))
            angle = math.atan2(float(self.sin[group].mean()), float(self.cos[group].mean())) % TAU
            gray_angle, gray_width = self.following_gray(white, circle, group)
            target = Target(angle, len(group) * TAU / 720, gray_angle, gray_width)
        radial = self.polar(red, circle, 0.52, 1.34, 45)
        strength = radial.mean(axis=0)
        # A narrow radial ridge distinguishes the needle from broad red flames.
        baseline = (np.roll(strength, 16) + np.roll(strength, -16)) / 2
        ridge = strength - baseline
        index = int(np.argmax(ridge))
        pointer = None
        pointer_width = 0.0
        if strength[index] > 0.34 and ridge[index] > 0.20:
            # Measure the visible needle shaft where it actually crosses the track.
            # argmax of a broad radial peak picks its first pixel and loses its width.
            ring_red = self.polar(red, circle, 0.94, 1.06, 17).mean(axis=0)
            local = (index + np.arange(-8, 9)) % len(self.angles)
            core = np.zeros(len(self.angles), dtype=bool)
            core[local] = ring_red[local] >= 0.72
            cores = [g for g in runs(core) if 1 <= len(g) <= 13]
            if cores:
                group = max(cores, key=lambda g: float(ring_red[g].sum()))
                weights = ring_red[group]
                pointer = (
                    math.atan2(
                        float((self.sin[group] * weights).sum()),
                        float((self.cos[group] * weights).sum()),
                    )
                    % TAU
                )
                pointer_width = len(group) * TAU / len(self.angles)
        return Observation((circle[0], circle[1]), circle[2], target, pointer, pointer_width)
