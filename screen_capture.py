import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import mss
import numpy as np

from input_controller import user32

user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]


def enable_dpi_awareness() -> None:
    # All capture and window coordinates are physical pixels, also at 125/150% DPI.
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except AttributeError:
        user32.SetProcessDPIAware()


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    def as_dict(self) -> dict[str, int]:
        return dict(left=self.left, top=self.top, width=self.width, height=self.height)


class ScreenCapture:
    def __init__(self):
        self.backend = mss.mss()
        self.client: Region | None = None
        self.region: Region | None = None
        self.locked = False

    def close(self) -> None:
        self.backend.close()

    def update_window(self, hwnd: int) -> bool:
        rect, point = wintypes.RECT(), wintypes.POINT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)) or not user32.ClientToScreen(
            hwnd, ctypes.byref(point)
        ):
            raise OSError("Cannot read Roblox window bounds")
        client = Region(point.x, point.y, rect.right, rect.bottom)
        if client.width < 100 or client.height < 100:
            raise OSError("Roblox window is minimized or too small")
        changed = client != self.client
        if changed:
            self.client = client
            self.unlock()
        return changed

    def unlock(self) -> None:
        if self.client is not None:
            c = self.client
            width, height = min(640, c.width), min(480, c.height)
            self.region = Region(
                c.left + (c.width - width) // 2, c.top + (c.height - height) // 2, width, height
            )
        self.locked = False

    def lock(self, center: tuple[float, float], radius: float) -> None:
        if self.region is None or self.client is None:
            return
        x, y = self.region.left + center[0], self.region.top + center[1]
        c = self.client
        pad = int(radius * 1.55) + 5
        left, top = max(c.left, int(x) - pad), max(c.top, int(y) - pad)
        right, bottom = min(c.left + c.width, int(x) + pad), min(c.top + c.height, int(y) + pad)
        self.region = Region(left, top, right - left, bottom - top)
        self.locked = True

    def grab(self) -> np.ndarray:
        if self.region is None:
            raise RuntimeError("Capture region is not set")
        return np.asarray(self.backend.grab(self.region.as_dict()))[:, :, :3]
