import math
import unittest

from indicator_tracker import IndicatorTracker
from skillcheck_detector import Observation, Target
from timing_predictor import TimingPredictor


def observation(target: float, pointer: float, width: float = 0.20) -> Observation:
    return Observation((100, 100), 68, Target(target, width), pointer)


class TimingTests(unittest.TestCase):
    def test_one_press_until_new_target(self):
        p = TimingPredictor()
        self.assertFalse(p.update(observation(1, 0.8), 4, 0).fire)
        self.assertTrue(p.update(observation(1, 1), 4, 0).fire)
        p.mark_fired()
        for _ in range(8):
            self.assertFalse(p.update(observation(1, 1), 4, 0).fire)
        # Endless check: unchanged circle, new target, immediate next shot allowed.
        self.assertFalse(p.update(observation(3, 2.8), 4, 0).fire)
        result = p.update(observation(3, 3), 4, 0)
        self.assertTrue(result.new_target)
        self.assertTrue(result.fire)

    def test_missing_target_does_not_rearm(self):
        p = TimingPredictor()
        p.update(observation(1, 1), 4, 0)
        p.update(observation(1, 1), 4, 0)
        p.mark_fired()
        p.update(Observation((100, 100), 68, None, 1), 4, 0)
        self.assertFalse(p.update(observation(1, 1), 4, 0).fire)

    def test_single_frame_false_target_does_not_rearm(self):
        p = TimingPredictor()
        p.update(observation(1, 1), 4, 0)
        p.update(observation(1, 1), 4, 0)
        p.mark_fired()
        p.update(observation(3, 3), 4, 0)
        self.assertFalse(p.update(observation(1, 1), 4, 0).fire)

    def test_ordinary_check_reset_allows_same_target(self):
        p = TimingPredictor()
        for _ in range(2):
            p.update(observation(1, 1), 4, 0)
        p.mark_fired()
        p.reset()
        p.update(observation(1, 1), 4, 0)
        self.assertTrue(p.update(observation(1, 1), 4, 0).fire)

    def test_latency_prediction_cannot_authorize_early_press(self):
        p = TimingPredictor()
        obs = observation(1, 0.88, 0.1)
        p.update(obs, 4, 0.03)
        self.assertFalse(p.update(obs, 4, 0.03).fire)

    def test_needle_occlusion_preserves_full_target(self):
        p = TimingPredictor()
        p.update(observation(1, 0.5), 4, 0)
        p.update(observation(1, 0.6), 4, 0)
        # Red needle covers one side; the visible white fragment shifts/shrinks.
        self.assertTrue(p.update(observation(1.05, 1, 0.10), 4, 0).fire)

    def test_wraparound_and_wrong_direction(self):
        tracker = IndicatorTracker()
        speeds = [
            tracker.update(a % (2 * math.pi), i * 0.02)
            for i, a in enumerate([6.2, 6.28, 6.36, 6.44])
        ]
        self.assertAlmostEqual(speeds[-1], 4)
        tracker.reset()
        for i in range(5):
            self.assertIsNone(tracker.update(2 - i * 0.08, i * 0.02))

    def test_fast_zone_between_two_captures_cannot_authorize_early_press(self):
        p = TimingPredictor()
        p.update(observation(1, 0.4, 0.10), 20, 0)
        result = p.update(observation(1, 0.6, 0.10), 20, 0)
        self.assertFalse(result.fire)

    def test_visible_interior_fires_without_a_blind_wait(self):
        p = TimingPredictor()
        p.update(observation(1, 0.93), 5, 0)
        result = p.update(observation(1, 0.93), 5, 0)
        self.assertTrue(result.fire)

    def test_completely_occluded_target_can_use_confirmed_geometry(self):
        p = TimingPredictor()
        p.update(observation(1, 0.5), 10, 0)
        p.update(observation(1, 0.6), 10, 0)
        result = p.update(Observation((100, 100), 68, None, 0.98), 10, 0)
        self.assertTrue(result.fire)

    def test_fast_motion_above_old_speed_limit(self):
        tracker = IndicatorTracker()
        for i in range(8):
            speed = tracker.update((i * 0.02 * 24) % (2 * math.pi), i * 0.02)
        self.assertAlmostEqual(speed, 24)

    def test_repeated_frame_keeps_motion_and_its_original_timestamp(self):
        tracker = IndicatorTracker()
        for i in range(5):
            tracker.update(i * 0.02 * 8, i * 0.02)
        self.assertAlmostEqual(tracker.update(0.64, 0.09), 8)
        self.assertAlmostEqual(tracker.sample_time, 0.08)
        self.assertIsNone(tracker.update(0.64, 0.17))

    def test_fast_crossing_requires_a_frame_inside_the_zone(self):
        p = TimingPredictor()
        p.update(observation(1, 0.2, 0.10), 16, 0)
        result = p.update(observation(1, 0.52, 0.10), 16, 0)
        self.assertFalse(result.fire)
        self.assertTrue(p.update(observation(1, 1, 0.10), 16, 0).fire)

    def test_prediction_past_the_exit_rejects_stale_inside_frame(self):
        p = TimingPredictor()
        obs = observation(1, 1.02, 0.10)
        p.update(obs, 10, 0.02)
        self.assertFalse(p.update(obs, 10, 0.02).fire)

    def test_visible_needle_edge_overlap_is_not_discarded(self):
        p = TimingPredictor()
        p.update(observation(1, 0.5, 0.10), 9, 0)
        p.update(observation(1, 0.6, 0.10), 9, 0)
        # Center is just outside, but 0.02 rad of the visible shaft overlaps white.
        obs = Observation((100, 100), 68, Target(1, 0.10), 0.94, 0.06)
        self.assertTrue(p.update(obs, 9, 0).fire)

    def test_gap_between_visible_needle_and_zone_blocks_even_with_prediction(self):
        p = TimingPredictor()
        p.update(observation(1, 0.5, 0.10), 9, 0)
        p.update(observation(1, 0.6, 0.10), 9, 0)
        obs = Observation((100, 100), 68, Target(1, 0.10), 0.90, 0.06)
        self.assertFalse(p.update(obs, 9, 0.01).fire)


if __name__ == "__main__":
    unittest.main()
