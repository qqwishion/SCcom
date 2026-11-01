"""Hold-to-run A/D alternation, independent of the capture worker."""

import logging
import threading
import time

from config import Config
from input_controller import foreground_roblox, send_scan, user32

log = logging.getLogger(__name__)


class MoonwalkController:
    def __init__(self, interval_ms: float = 53, gap_ms: float = 10):
        self.interval_s = interval_ms / 1000
        self.gap_s = gap_ms / 1000
        self.held_scan: int | None = None
        self.hwnd: int | None = None
        self.next_change = 0.0
        self.next_scan = 0x1E  # A, then D (0x20)

    def release(self) -> None:
        if self.held_scan is not None:
            send_scan(self.held_scan, True)
            self.held_scan = None
        self.hwnd = None
        self.next_change = 0.0
        self.next_scan = 0x1E

    def update(self, enabled: bool, hwnd: int | None, now: float) -> None:
        if not enabled or hwnd is None:
            self.release()
            return
        if self.hwnd is not None and self.hwnd != hwnd:
            self.release()
            return
        if now < self.next_change:
            return
        if self.held_scan is not None:
            send_scan(self.held_scan, True)
            self.held_scan = None
            self.next_change = now + self.gap_s
            return
        # Recheck focus immediately before keydown.
        if foreground_roblox() != hwnd:
            self.release()
            return
        send_scan(self.next_scan, False)
        self.held_scan = self.next_scan
        self.next_scan = 0x20 if self.next_scan == 0x1E else 0x1E
        self.hwnd = hwnd
        # Missed deadlines are not replayed in a burst.
        self.next_change = now + self.interval_s


class Moonwalk:
    def __init__(self, config: Config):
        self.config = config
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, name="Moonwalk", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        controller = MoonwalkController(
            self.config.moonwalk_interval_ms, self.config.moonwalk_gap_ms
        )
        try:
            while not self.stop_event.is_set():
                try:
                    enabled = self.config.send_input and bool(
                        user32.GetAsyncKeyState(self.config.moonwalk_hold_vk) & 0x8000
                    )
                    hwnd = foreground_roblox() if enabled else None
                    controller.update(enabled, hwnd, time.perf_counter())
                except Exception:
                    log.exception("Moonwalk input failure")
                    try:
                        controller.release()
                    except OSError:
                        log.exception("Moonwalk key release failed; will retry")
                    self.stop_event.wait(0.1)
                self.stop_event.wait(0.005)
        finally:
            for _ in range(3):
                try:
                    controller.release()
                    break
                except OSError:
                    log.exception("Moonwalk shutdown key release failed")
