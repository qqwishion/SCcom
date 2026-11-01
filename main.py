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
        "--moonwalk-ms",
        type=float,
        default=CONFIG.moonwalk_interval_ms,
        help="Длительность зажатия A/D при удержании Caps Lock, мс (20–200; по умолчанию 53)",
    )
    parser.add_argument(
        "--observe", action="store_true", help="Только наблюдение, без отправки пробела"
    )
    args = parser.parse_args()
    if not 20 <= args.moonwalk_ms <= 200:
        parser.error("--moonwalk-ms должен быть от 20 до 200")
    if sys.platform != "win32":
        parser.error("Для захвата и отправки пробела требуется Windows")
    import tkinter as tk

    from engine import Engine
    from moonwalk import Moonwalk
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
        "Startup: dxgi-gray-v6 repeat_guard=per_target observe=%s",
        args.observe,
    )
    if args.smoke_test:
        from screen_capture import Region, ScreenCapture
        from skillcheck_detector import SkillcheckDetector

        SkillcheckDetector(CONFIG.min_radius, CONFIG.max_radius)
        smoke_capture = ScreenCapture()
        try:
            smoke_capture.region = Region(0, 0, 64, 64)
            smoke_capture.grab()
            logging.info("Smoke capture backend=%s", smoke_capture.name)
        finally:
            smoke_capture.close()
    config = replace(
        CONFIG,
        input_lead_ms=args.lead_ms,
        send_input=not args.observe,
        moonwalk_interval_ms=args.moonwalk_ms,
    )
    engine = Engine(config)
    moonwalk = Moonwalk(config)
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
        moonwalk.stop()
        root.withdraw()
        crosshair.withdraw()

        # Key-up completes before the process is allowed to exit.
        def wait_worker() -> None:
            if engine.thread.is_alive() or moonwalk.thread.is_alive():
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
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    crosshair = tk.Toplevel(root)
    crosshair.withdraw()
    crosshair.overrideredirect(True)
    crosshair.attributes("-topmost", True)
    crosshair.attributes("-transparentcolor", "#ff00ff")
    crosshair.configure(bg="#ff00ff")
    crosshair.geometry(
        f"10x10+{root.winfo_screenwidth() // 2 - 5}+{root.winfo_screenheight() // 2 - 5}"
    )
    canvas = tk.Canvas(crosshair, width=10, height=10, bg="#ff00ff", highlightthickness=0, bd=0)
    canvas.pack()
    canvas.create_oval(3, 3, 7, 7, fill="white", outline="white")
    crosshair.update_idletasks()
    crosshair_hwnd = u.GetParent(crosshair.winfo_id())
    crosshair_style = u.GetWindowLongW(crosshair_hwnd, -20)
    # Layered, click-through, non-activating tool window.
    u.SetWindowLongW(crosshair_hwnd, -20, crosshair_style | 0x00080000 | 0x00000020 | 0x08000080)
    crosshair_visible = False
    ui_visible = True
    f10_down = bool(u.GetAsyncKeyState(0x79) & 0x8000)
    f8_down = bool(u.GetAsyncKeyState(0x77) & 0x8000)

    def toggle_crosshair() -> None:
        nonlocal crosshair_visible
        crosshair_visible = not crosshair_visible
        if crosshair_visible:
            crosshair.deiconify()
        else:
            crosshair.withdraw()
        logging.info("Crosshair visible=%s", crosshair_visible)

    def toggle_ui() -> None:
        nonlocal ui_visible
        ui_visible = not ui_visible
        if ui_visible:
            root.deiconify()
        else:
            root.withdraw()
        logging.info("UI visible=%s", ui_visible)

    def check_hotkey() -> None:
        nonlocal f10_down, f8_down
        pressed = bool(u.GetAsyncKeyState(0x79) & 0x8000)
        if pressed and not f10_down:
            toggle_ui()
        f10_down = pressed
        pressed = bool(u.GetAsyncKeyState(0x77) & 0x8000)
        if pressed and not f8_down:
            toggle_crosshair()
        f8_down = pressed
        root.after(20, check_hotkey)

    def refresh() -> None:
        s = engine.snapshot()
        heading = "VDchecker · БЕЗ НАЖАТИЙ" if args.observe else "VDchecker · ВКЛ"
        label.configure(text=f"{heading}\n{s.text}")
        root.after(250, refresh)

    if args.smoke_test:

        def smoke_toggle() -> None:
            assert crosshair.state() == "withdrawn"
            toggle_crosshair()
            root.update_idletasks()
            assert crosshair.state() == "normal"
            toggle_ui()
            root.update_idletasks()
            assert root.state() == "withdrawn"
            assert crosshair.winfo_ismapped()
            toggle_ui()
            root.update_idletasks()
            assert root.state() == "normal"
            toggle_crosshair()
            assert crosshair.state() == "withdrawn"
            logging.info("Smoke crosshair toggle passed")
            logging.info("Smoke UI hide/show passed")

        root.after(100, smoke_toggle)
        root.after(500, close)
    else:
        engine.start()
        moonwalk.start()
    refresh()
    check_hotkey()
    try:
        root.mainloop()
    finally:
        engine.stop()
        moonwalk.stop()
        if engine.thread.ident is not None:
            engine.thread.join(timeout=2)
        if moonwalk.thread.ident is not None:
            moonwalk.thread.join(timeout=2)


if __name__ == "__main__":
    from single_instance import single_instance

    if "--smoke-test" in sys.argv:
        main()
    else:
        with single_instance() as acquired:
            if acquired:
                main()
