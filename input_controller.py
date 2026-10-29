"""Windows keyboard input, guarded by the current foreground window."""

import ctypes
import time
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUTUNION)]


user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


def foreground_roblox() -> int | None:
    hwnd = user32.GetForegroundWindow()
    text = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, text, len(text))
    return hwnd if text.value.strip().lower() == "roblox" else None


class InputController:
    def __init__(self, hold_ms: float = 12, min_interval_ms: float = 50):
        self.hold_s = hold_ms / 1000
        self.min_interval_s = min_interval_ms / 1000
        self.next_allowed_press = float("-inf")

    @staticmethod
    def send(up: bool) -> None:
        event = INPUT(type=1, ki=KEYBDINPUT(0, 0x39, 0x0008 | (0x0002 if up else 0), 0, 0))
        if user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(INPUT)) != 1:
            raise OSError(ctypes.get_last_error(), "SendInput failed")

    def tap_space(self, expected_hwnd: int) -> float | None:
        # Global guard, independent of detector/target resets. Never queue a blocked tap.
        if time.perf_counter() < self.next_allowed_press:
            return None
        if foreground_roblox() != expected_hwnd or user32.GetAsyncKeyState(0x20) & 0x8000:
            return None
        start = time.perf_counter()
        self.send(False)
        pressed_at = time.perf_counter()
        self.next_allowed_press = pressed_at + self.min_interval_s
        down_ms = (pressed_at - start) * 1000
        try:
            time.sleep(self.hold_s)
        finally:
            self.send(True)
        return down_ms
