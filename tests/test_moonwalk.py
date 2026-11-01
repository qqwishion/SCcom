import threading
import unittest
from unittest.mock import call, patch

from config import Config
from moonwalk import Moonwalk, MoonwalkController


class MoonwalkTests(unittest.TestCase):
    def setUp(self):
        self.send = patch("moonwalk.send_scan").start()
        self.focus = patch("moonwalk.foreground_roblox", return_value=123).start()
        self.addCleanup(patch.stopall)
        self.controller = MoonwalkController(35)

    def test_inactive_does_not_send(self):
        self.controller.update(False, 123, 1)
        self.controller.update(True, None, 2)
        self.send.assert_not_called()

    def test_alternates_without_overlapping_keys(self):
        for now in (1.0, 1.01, 1.036, 1.072):
            self.controller.update(True, 123, now)
        self.assertEqual(
            self.send.call_args_list,
            [
                call(0x1E, False),
                call(0x1E, True),
                call(0x20, False),
                call(0x20, True),
                call(0x1E, False),
            ],
        )

    def test_release_before_next_deadline_and_restart(self):
        self.controller.update(True, 123, 1)
        self.controller.update(False, 123, 1.001)
        self.controller.update(False, 123, 1.002)
        self.controller.update(True, 123, 1.003)
        self.assertEqual(
            self.send.call_args_list,
            [
                call(0x1E, False),
                call(0x1E, True),
                call(0x1E, False),
            ],
        )

    def test_focus_loss_releases_immediately(self):
        self.controller.update(True, 123, 1)
        self.controller.update(True, None, 1.001)
        self.assertEqual(self.send.call_args_list, [call(0x1E, False), call(0x1E, True)])

    def test_different_window_releases_without_pressing(self):
        self.controller.update(True, 123, 1)
        self.controller.update(True, 456, 1.001)
        self.send.assert_called_with(0x1E, True)
        self.assertIsNone(self.controller.held_scan)

    def test_focus_change_at_dispatch_blocks_keydown(self):
        self.focus.return_value = None
        self.controller.update(True, 123, 1)
        self.send.assert_not_called()

    def test_delayed_tick_does_not_replay_missed_pulses(self):
        self.controller.update(True, 123, 1)
        self.controller.update(True, 123, 2)
        self.assertEqual(self.send.call_count, 3)

    def test_failed_release_retains_ownership_for_retry(self):
        self.controller.update(True, 123, 1)
        self.send.side_effect = OSError("blocked")
        with self.assertRaises(OSError):
            self.controller.release()
        self.assertEqual(self.controller.held_scan, 0x1E)
        self.send.side_effect = None
        self.controller.release()
        self.assertIsNone(self.controller.held_scan)

    def test_worker_shutdown_releases_held_key(self):
        worker = Moonwalk(Config())
        with patch("moonwalk.user32.GetAsyncKeyState", return_value=0x8000):

            def send(scan, up):
                if not up:
                    worker.stop()

            self.send.side_effect = send
            worker.start()
            worker.thread.join(timeout=1)
        self.assertFalse(worker.thread.is_alive())
        self.assertEqual(self.send.call_args_list, [call(0x1E, False), call(0x1E, True)])

    def test_observe_mode_never_sends_movement(self):
        worker = Moonwalk(Config(send_input=False))
        checked = threading.Event()
        with patch(
            "moonwalk.time.perf_counter",
            side_effect=lambda: (checked.set(), worker.stop(), 1.0)[-1],
        ):
            worker.start()
            worker.thread.join(timeout=1)
        self.assertTrue(checked.is_set())
        self.assertFalse(worker.thread.is_alive())
        self.send.assert_not_called()
