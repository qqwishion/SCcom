import ctypes
import logging
import threading
import time
from dataclasses import dataclass, replace

import cv2

from config import CONFIG, Config
from indicator_tracker import IndicatorTracker
from input_controller import InputController, foreground_roblox
from screen_capture import ScreenCapture
from skillcheck_detector import SkillcheckDetector
from timing_predictor import TimingPredictor

log = logging.getLogger(__name__)


@dataclass
class Status:
    text: str = "Откройте Roblox"


class Engine:
    def __init__(self, config: Config = CONFIG):
        self.config = config
        self.stop_event = threading.Event()
        self.status = Status()
        self.guard = threading.Lock()
        self.thread = threading.Thread(target=self.run, name="VDchecker", daemon=True)

    def snapshot(self) -> Status:
        with self.guard:
            return replace(self.status)

    def set_status(self, text: str) -> None:
        with self.guard:
            self.status.text = text

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        cv2.setNumThreads(1)
        detector = SkillcheckDetector(self.config.min_radius, self.config.max_radius)
        tracker, predictor = IndicatorTracker(), TimingPredictor()
        keyboard = InputController(self.config.key_hold_ms)
        capture: ScreenCapture | None = None
        timer = ctypes.WinDLL("winmm")
        timer_active = timer.timeBeginPeriod(1) == 0
        last_seen, next_search = 0.0, 0.0
        previous_hwnd = None
        last_sent_time: float | None = None
        missing_since: float | None = None
        loss_logged = True
        try:
            while not self.stop_event.is_set():
                cycle = time.perf_counter()
                hwnd = foreground_roblox()
                if hwnd is None:
                    self.set_status("Откройте Roblox")
                    detector.reset()
                    tracker.reset()
                    predictor.reset()
                    previous_hwnd = None
                    if capture:
                        capture.unlock()
                    self.stop_event.wait(0.08)
                    continue
                try:
                    if capture is None:
                        capture = ScreenCapture()
                    if capture.update_window(hwnd) or hwnd != previous_hwnd:
                        detector.reset()
                        tracker.reset()
                        predictor.reset()
                    previous_hwnd = hwnd
                    # Expensive circle acquisition runs at most 20 times per second.
                    if detector.circle is None and cycle < next_search:
                        self.stop_event.wait(min(0.01, next_search - cycle))
                        continue
                    capture_start = time.perf_counter()
                    frame = capture.grab()
                    captured = time.perf_counter()
                    # MSS can wait for a desktop refresh. The returned image arrives
                    # at the end of that wait; its duration is not added as frame age.
                    timestamp = captured
                    observation = detector.detect(frame)
                    now = time.perf_counter()
                    frame_ms = (now - capture_start) * 1000
                    if observation is None:
                        if missing_since is None:
                            missing_since = now
                        next_search = now + 0.05
                        self.set_status("Ожидание скиллчека")
                        if now - last_seen > self.config.missing_reset_s:
                            if not loss_logged:
                                since_press = (
                                    (missing_since - last_sent_time) * 1000
                                    if last_sent_time is not None
                                    else None
                                )
                                log.info(
                                    "Skillcheck disappeared: ms_since_space=%s observe=%s",
                                    "none" if since_press is None else f"{since_press:.1f}",
                                    not self.config.send_input,
                                )
                                loss_logged = True
                            tracker.reset()
                            predictor.reset()
                            capture.unlock()
                            detector.reset()
                    else:
                        last_seen = now
                        missing_since = None
                        loss_logged = False
                        speed = (
                            tracker.update(observation.pointer, timestamp)
                            if observation.pointer is not None
                            else None
                        )
                        pointer_time = (
                            tracker.sample_time if tracker.sample_time is not None else timestamp
                        )
                        lead = now - pointer_time + self.config.input_lead_ms / 1000
                        decision = predictor.update(observation, speed, lead)
                        if decision.new_target:
                            log.info(
                                "New target angle=%.3f width=%.3f",
                                observation.target.angle,
                                observation.target.width,
                            )
                        self.set_status(
                            "Слежение за стрелкой" if speed is not None else "Определение скорости"
                        )
                        if decision.fire and not self.stop_event.is_set():
                            actual = time.perf_counter()
                            # Reject a decision that became stale before dispatch.
                            safe_lateness = max(
                                0.001,
                                predictor.target.overlap_half_width(observation.pointer_width)
                                / speed
                                + min(0.0, decision.eta_ms / 1000),
                            )
                            if actual - now > safe_lateness:
                                log.warning(
                                    "Skipped stale decision: %.2f ms", (actual - now) * 1000
                                )
                                continue
                            if not self.config.send_input:
                                predictor.mark_fired()
                                log.info("Observe: would press space; speed=%.3f", speed)
                                continue
                            sent = keyboard.tap_space(hwnd, predictor.target_id)
                            if sent is not None:
                                last_sent_time = actual
                                predictor.mark_fired()
                                log.info(
                                    "Space: speed=%.3f eta_ms=%.2f dispatch_ms=%.2f frame_ms=%.2f capture_ms=%.2f send_ms=%.3f needle_width=%.4f",
                                    speed,
                                    decision.eta_ms,
                                    (actual - now) * 1000,
                                    frame_ms,
                                    (captured - capture_start) * 1000,
                                    sent,
                                    observation.pointer_width,
                                )
                        if not capture.locked:
                            old_region = capture.region
                            capture.lock(observation.center, observation.radius)
                            # Translate the existing circle into the smaller capture;
                            # do not repeat Hough acquisition at the critical moment.
                            detector.circle = (
                                old_region.left + observation.center[0] - capture.region.left,
                                old_region.top + observation.center[1] - capture.region.top,
                                observation.radius,
                            )
                            detector.maps.clear()
                except Exception:
                    log.exception("Capture/input failure")
                    self.set_status("Ошибка — см. vdchecker.log")
                    detector.reset()
                    tracker.reset()
                    predictor.reset()
                    if capture:
                        capture.close()
                        capture = None
                    self.stop_event.wait(0.5)
                remaining = 1 / self.config.capture_hz - (time.perf_counter() - cycle)
                if remaining > 0:
                    self.stop_event.wait(remaining)
        except Exception:
            log.exception("Worker stopped")
            self.set_status("Ошибка — перезапустите софт")
        finally:
            if capture:
                capture.close()
            if timer_active:
                timer.timeEndPeriod(1)
