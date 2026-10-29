import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from screen_capture import Region, ScreenCapture


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.camera = Mock(width=1920, height=1080)
        self.camera.grab.return_value = None
        self.mss = Mock()
        self.mss.grab.return_value = np.zeros((64, 64, 4), dtype=np.uint8)
        self.fake_dxcam = SimpleNamespace(
            output_info=lambda: "Device[0] Output[0]: Res:(1920, 1080) Rot:0 Primary:True",
            create=Mock(return_value=self.camera),
        )
        modules = patch.dict(sys.modules, {"dxcam": self.fake_dxcam})
        factory = patch("screen_capture.mss.mss", return_value=self.mss)
        modules.start()
        factory.start()
        self.addCleanup(modules.stop)
        self.addCleanup(factory.stop)

    def capture(self):
        capture = ScreenCapture()
        capture.region = Region(10, 10, 64, 64)
        self.addCleanup(capture.close)
        return capture

    def test_no_new_dxgi_frame_does_not_fall_back_or_invent_a_frame(self):
        capture = self.capture()
        self.assertIsNone(capture.grab())
        self.assertEqual(capture.name, "DXGI")
        self.mss.grab.assert_not_called()

    def test_new_dxgi_frame_is_returned(self):
        capture = self.capture()
        expected = np.zeros((64, 64, 3), dtype=np.uint8)
        self.camera.grab.return_value = expected
        self.assertIs(capture.grab(), expected)

    def test_dxgi_failure_uses_mss(self):
        capture = self.capture()
        self.camera.grab.side_effect = RuntimeError("test DXGI failure")
        with self.assertLogs("screen_capture", level="WARNING"):
            frame = capture.grab()
        self.assertEqual(capture.name, "MSS")
        self.assertEqual(frame.shape, (64, 64, 3))
        self.camera.release.assert_called_once()

    def test_region_on_other_monitor_uses_mss(self):
        capture = self.capture()
        capture.region = Region(-100, 10, 64, 64)
        self.assertEqual(capture.grab().shape, (64, 64, 3))
        self.assertEqual(capture.name, "MSS")
        self.camera.grab.assert_not_called()

    def test_unavailable_primary_output_uses_mss(self):
        self.fake_dxcam.output_info = lambda: ""
        with self.assertLogs("screen_capture", level="WARNING"):
            capture = self.capture()
        self.assertEqual(capture.name, "MSS")
        self.assertEqual(capture.grab().shape, (64, 64, 3))
