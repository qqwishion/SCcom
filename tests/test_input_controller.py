import unittest
from unittest.mock import patch

from input_controller import InputController


class CooldownTests(unittest.TestCase):
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

    def test_blocks_repeat_before_50ms_and_allows_at_boundary(self):
        self.assertIsNotNone(self.controller.tap_space(123))
        self.now = 10.049
        self.assertIsNone(self.controller.tap_space(123))
        self.now = 10.050
        self.assertIsNotNone(self.controller.tap_space(123))
        self.assertEqual(InputController.send.call_count, 4)  # two down/up pairs

    def test_focus_change_does_not_clear_cooldown(self):
        self.controller.tap_space(123)
        self.focus.stop()
        with patch("input_controller.foreground_roblox", return_value=456):
            self.now = 10.020
            self.assertIsNone(self.controller.tap_space(456))
            self.now = 10.051
            self.assertIsNotNone(self.controller.tap_space(456))

    def test_failed_keydown_does_not_start_cooldown(self):
        InputController.send.side_effect = OSError("test failure")
        with self.assertRaises(OSError):
            self.controller.tap_space(123)
        InputController.send.side_effect = None
        self.assertIsNotNone(self.controller.tap_space(123))


if __name__ == "__main__":
    unittest.main()
