"""Offline validation on recordings. Never imports keyboard/capture code."""

import argparse
import csv
import time
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np

from config import CONFIG
from indicator_tracker import IndicatorTracker
from skillcheck_detector import SkillcheckDetector
from timing_predictor import TimingPredictor


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка видео без отправки клавиш")
    parser.add_argument("video", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/replay.csv"))
    args = parser.parse_args()
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        parser.error(f"Cannot open {args.video}")
    cv2.setNumThreads(1)
    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        parser.error("Video has no usable frame rate")
    detector, tracker, predictor = SkillcheckDetector(), IndicatorTracker(), TimingPredictor()
    rows, costs, shots = [], [], []
    seen, targets, frames, last_seen = 0, 0, 0, -10.0
    box = None
    locked = False
    next_search = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            timestamp = frames / fps
            h, w = frame.shape[:2]
            base = (
                max(0, w // 2 - 320),
                max(0, h // 2 - 240),
                min(w, w // 2 + 320),
                min(h, h // 2 + 240),
            )
            if box is None:
                box = base
            left, top, right, bottom = box
            roi = frame[top:bottom, left:right]
            start = time.perf_counter()
            observation = (
                detector.detect(roi)
                if detector.circle is not None or timestamp >= next_search
                else None
            )
            speed = None
            fire = False
            scheduled_time: float | str = ""
            if observation:
                seen += 1
                last_seen = timestamp
                speed = (
                    tracker.update(observation.pointer, timestamp)
                    if observation.pointer is not None
                    else None
                )
                # Evaluate visible crossings, without assuming unmeasurable video/input latency.
                pointer_time = tracker.sample_time if tracker.sample_time is not None else timestamp
                decision = predictor.update(observation, speed, timestamp - pointer_time)
                targets += int(decision.new_target)
                fire = decision.fire
                if fire:
                    scheduled_time = timestamp
                    shots.append(
                        (
                            scheduled_time,
                            replace(
                                observation,
                                center=(left + observation.center[0], top + observation.center[1]),
                            ),
                        )
                    )
                    predictor.mark_fired()
                if not locked:
                    x, y = left + observation.center[0], top + observation.center[1]
                    pad = int(observation.radius * 1.55) + 5
                    box = (
                        max(0, int(x) - pad),
                        max(0, int(y) - pad),
                        min(w, int(x) + pad),
                        min(h, int(y) + pad),
                    )
                    detector.circle = (x - box[0], y - box[1], observation.radius)
                    detector.maps.clear()
                    locked = True
            elif timestamp - last_seen > CONFIG.missing_reset_s:
                predictor.reset()
                tracker.reset()
                box, locked = base, False
                detector.reset()
            if observation is None and timestamp >= next_search:
                next_search = timestamp + 0.05
            costs.append((time.perf_counter() - start) * 1000)
            rows.append(
                [
                    frames,
                    timestamp,
                    bool(observation),
                    observation.target.angle if observation and observation.target else "",
                    observation.pointer if observation else "",
                    speed or "",
                    fire,
                    scheduled_time,
                ]
            )
            frames += 1
    finally:
        cap.release()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "frame",
                "time_s",
                "circle",
                "target_rad",
                "pointer_rad",
                "speed_rad_s",
                "would_press",
                "scheduled_time_s",
            ]
        )
        writer.writerows(rows)
    # Native OpenCV contact sheet documents each predicted press in the original recording.
    if shots:
        sheet = np.zeros((((len(shots) + 3) // 4) * 250, 4 * 240, 3), dtype=np.uint8)
        cap = cv2.VideoCapture(str(args.video))
        for i, (timestamp, observation) in enumerate(shots):
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            h, w = frame.shape[:2]
            x, y = observation.center
            crop = frame[max(0, int(y) - 110) : int(y) + 110, max(0, int(x) - 110) : int(x) + 110]
            crop = cv2.resize(crop, (220, 220))
            left, top = (i % 4) * 240, (i // 4) * 250
            sheet[top : top + 220, left : left + 220] = crop
            cv2.putText(
                sheet,
                f"{timestamp:.3f}s",
                (left + 3, top + 240),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 255, 255),
                1,
            )
        cap.release()
        cv2.imencode(".jpg", sheet)[1].tofile(str(args.output.with_suffix(".jpg")))
    print(
        f"Frames={frames}; circle_frames={seen}; target_events={targets}; simulated_presses={len(shots)}"
    )
    print(f"Detector+timing ms: median={np.median(costs):.2f}; p95={np.percentile(costs, 95):.2f}")
    print("Simulated press times:", ", ".join(f"{t:.3f}" for t, _ in shots))
    print(f"Report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
