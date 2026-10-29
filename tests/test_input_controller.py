import unittest
from unittest.mock import patch

from input_controller import InputController


class TargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.clock = patch("input_controller.time.perf_counter", side_effect=lambda: self.now)
        self.sleep = patch("input_controller.time.sleep")
        self.focus = patch("input_controller.foreground_roblox", return_value=123)
        self.keys = patch("input_controller.user32.GetAsyncKeyState", return_value=0)
        self.send = patch.object(InputController, "send")
        for p in (self.clock, self.sleep, self.focus, self.keys, self.send):
            p.start()
            self.addCleanup(p.stop)
        self.controller = InputController()
        self.target = object()

    def test_new_target_is_allowed_after_20ms(self):
        self.assertIsNotNone(self.controller.tap_space(123, self.target))
        self.now = 10.020
        self.assertIsNotNone(self.controller.tap_space(123, object()))
        self.assertEqual(InputController.send.call_count, 4)  # two down/up pairs

    def test_same_target_stays_blocked_after_50ms(self):
        self.controller.tap_space(123, self.target)
        for timestamp in (10.020, 10.050, 11.0):
            self.now = timestamp
            self.assertIsNone(self.controller.tap_space(123, self.target))
        self.assertEqual(InputController.send.call_count, 2)

    def test_focus_change_does_not_rearm_the_same_target(self):
        self.controller.tap_space(123, self.target)
        self.focus.stop()
        with patch("input_controller.foreground_roblox", return_value=456):
            self.now = 10.020
            self.assertIsNone(self.controller.tap_space(456, self.target))
            self.now = 10.051
            self.assertIsNone(self.controller.tap_space(456, self.target))
            self.assertIsNotNone(self.controller.tap_space(456, object()))

    def test_failed_keydown_does_not_consume_target(self):
        InputController.send.side_effect = OSError("test failure")
        with self.assertRaises(OSError):
            self.controller.tap_space(123, self.target)
        InputController.send.side_effect = None
        self.assertIsNotNone(self.controller.tap_space(123, self.target))


if __name__ == "__main__":
    unittest.main()
