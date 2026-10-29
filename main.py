import argparse
import ctypes
import logging
import os
import sys
from dataclasses import replace
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config import CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description="VDchecker: автоматические скиллчеки VD")
    parser.add_argument(
        "--lead-ms",
        type=float,
        default=CONFIG.input_lead_ms,
        help="Поправка задержки для проверки выхода из зоны, мс (по умолчанию 0)",
    )
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--observe", action="store_true", help="Только наблюдение, без отправки пробела"
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Для захвата и отправки пробела требуется Windows")
    import tkinter as tk

    from engine import Engine
    from screen_capture import enable_dpi_awareness

    enable_dpi_awareness()
    if getattr(sys, "frozen", False):
        log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "VDchecker"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "vdchecker.log"
    else:
        log_path = Path(__file__).with_name("vdchecker.log")
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s pid=%(process)d %(levelname)s %(message)s",
    )
    logging.info(
        "Startup: visible-overlap-v4 cooldown_ms=%.1f observe=%s",
        CONFIG.min_press_interval_ms,
        args.observe,
    )
    if args.smoke_test:
        from skillcheck_detector import SkillcheckDetector

        SkillcheckDetector(CONFIG.min_radius, CONFIG.max_radius)
    engine = Engine(replace(CONFIG, input_lead_ms=args.lead_ms, send_input=not args.observe))
    root = tk.Tk()
    root.title("VDchecker")
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.78)
    root.configure(bg="#181c23")
    root.geometry(f"270x66+{max(0, root.winfo_screenwidth() - 270 - 16)}+16")
    label = tk.Label(
        root, text="VDchecker · ВКЛ", fg="#8fe3a2", bg="#181c23", font=("Segoe UI", 10), anchor="w"
    )
    label.pack(side="left", padx=12, fill="both", expand=True)

    def close() -> None:
        engine.stop()
        root.withdraw()

        # Key-up completes before the process is allowed to exit.
        def wait_worker() -> None:
            if engine.thread.is_alive():
                root.after(20, wait_worker)
            else:
                root.destroy()

        wait_worker()

    tk.Button(
        root,
        text="×",
        command=close,
        bg="#303640",
        fg="white",
        activebackground="#943c48",
        activeforeground="white",
        bd=0,
        font=("Segoe UI", 17),
        cursor="hand2",
        width=3,
    ).pack(side="right", fill="y")
    root.protocol("WM_DELETE_WINDOW", close)
    root.update_idletasks()
    # Non-activating tool window: clicking the close button preserves game focus.
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.GetParent.argtypes = [ctypes.c_void_p]
    u.GetParent.restype = ctypes.c_void_p
    u.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
    hwnd = u.GetParent(root.winfo_id())
    style = u.GetWindowLongW(hwnd, -20)
    u.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)

    def refresh() -> None:
        s = engine.snapshot()
        heading = "VDchecker · БЕЗ НАЖАТИЙ" if args.observe else "VDchecker · ВКЛ"
        label.configure(text=f"{heading}\n{s.text}")
        root.after(250, refresh)

    if args.smoke_test:
        root.after(500, close)
    else:
        engine.start()
    refresh()
    try:
        root.mainloop()
    finally:
        engine.stop()
        if engine.thread.ident is not None:
            engine.thread.join(timeout=2)


if __name__ == "__main__":
    from single_instance import single_instance

    if "--smoke-test" in sys.argv:
        main()
    else:
        with single_instance() as acquired:
            if acquired:
                main()
