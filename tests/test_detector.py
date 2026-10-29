import math
import unittest
from pathlib import Path

import cv2
import numpy as np

from skillcheck_detector import SkillcheckDetector, difference, runs
from timing_predictor import TimingPredictor


class DetectorTests(unittest.TestCase):
    def test_ring_target_and_red_needle(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.circle(frame, (150, 150), 68, (210, 210, 210), 1, cv2.LINE_AA)
        cv2.rectangle(frame, (78, 144), (86, 156), (255, 255, 255), -1)
        icon = cv2.imread(str(Path(__file__).parents[1] / "assets" / "space_template.png"))
        frame[132:169, 117:183] = icon
        cv2.line(frame, (150, 185), (150, 241), (30, 30, 220), 3)
        obs = SkillcheckDetector().detect(frame)
        self.assertIsNotNone(obs)
        self.assertLess(abs(obs.radius - 68), 2)
        self.assertLess(abs(difference(obs.target.angle, 1.5 * math.pi)), 0.05)
        self.assertLess(abs(difference(obs.pointer, math.pi)), 0.05)
        self.assertIsNone(obs.target.gray_angle)

    def test_plain_scenery_does_not_trigger(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.rectangle(frame, (50, 50), (250, 250), (255, 255, 255), 2)
        cv2.line(frame, (150, 150), (150, 240), (0, 0, 255), 3)
        self.assertIsNone(SkillcheckDetector().detect(frame))

    def test_circular_target_straddling_top(self):
        groups = runs(np.array([True, True, False, False, True]))
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {0, 1, 4})

    def test_recorded_fast_crossing_requires_visible_overlap(self):
        detector, predictor = SkillcheckDetector(), TimingPredictor()
        fixtures = Path(__file__).parent / "fixtures"
        clean = detector.detect(cv2.imread(str(fixtures / "clear_target.png")))
        self.assertIsNotNone(clean)
        predictor.update(clean, 9, 0)
        predictor.update(clean, 9, 0)
        before = detector.detect(cv2.imread(str(fixtures / "before_overlap.png")))
        self.assertFalse(predictor.update(before, 9, 0).fire)
        overlap = detector.detect(cv2.imread(str(fixtures / "visible_overlap.png")))
        self.assertGreater(overlap.pointer_width, 0)
        self.assertTrue(predictor.update(overlap, 9, 0).fire)

    def test_outline_following_white_is_detected_as_gray_region(self):
        frame = np.zeros((300, 300, 3), dtype=np.uint8)
        cv2.circle(frame, (150, 150), 68, (210, 210, 210), 1, cv2.LINE_AA)
        cv2.ellipse(frame, (150, 150), (68, 68), 0, 5, 45, (0, 0, 0), 12)
        for radius in (63, 73):
            cv2.ellipse(
                frame, (150, 150), (radius, radius), 0, 5, 45, (230, 230, 230), 1, cv2.LINE_AA
            )
        cv2.ellipse(frame, (150, 150), (68, 68), 0, -5, 5, (255, 255, 255), 10, cv2.LINE_AA)
        icon = cv2.imread(str(Path(__file__).parents[1] / "assets" / "space_template.png"))
        frame[132:169, 117:183] = icon
        cv2.line(frame, (150, 115), (150, 60), (20, 20, 220), 3)
        obs = SkillcheckDetector().detect(frame)
        self.assertIsNotNone(obs)
        self.assertIsNotNone(obs.target.gray_angle)
        self.assertGreater(obs.target.gray_width, math.radians(20))
        self.assertGreater((obs.target.gray_angle - obs.target.angle) % (2 * math.pi), 0)

    def test_recorded_gray_sector_recovers_a_missed_white_frame(self):
        detector, predictor = SkillcheckDetector(), TimingPredictor()
        fixtures = Path(__file__).parent / "fixtures"
        clean = detector.detect(cv2.imread(str(fixtures / "gray_target.png")))
        self.assertIsNotNone(clean.target.gray_angle)
        predictor.update(clean, 13, 0)
        predictor.update(clean, 13, 0)
        token = predictor.target_id
        late = detector.detect(cv2.imread(str(fixtures / "gray_hit.png")))
        result = predictor.update(late, 13, 0)
        self.assertTrue(result.fire)
        self.assertEqual(result.zone, "gray")
        self.assertIs(token, predictor.target_id)
        predictor.mark_fired()
        self.assertFalse(predictor.update(late, 13, 0).fire)


if __name__ == "__main__":
    unittest.main()
