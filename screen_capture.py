import ctypes
import logging
import re
from ctypes import wintypes
from dataclasses import dataclass

import mss
import numpy as np

from input_controller import user32

log = logging.getLogger(__name__)

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
        self.camera = None
        self.name = "MSS"
        try:
            import dxcam

            primary = re.search(
                r"Device\[(\d+)\] Output\[(\d+)\].*Primary:True", dxcam.output_info()
            )
            if primary is None:
                raise RuntimeError("Cannot identify primary DXGI output")
            self.camera = dxcam.create(
                device_idx=int(primary[1]), output_idx=int(primary[2]), output_color="BGR"
            )
            self.name = "DXGI"
            log.info("Capture backend: DXGI")
        except Exception:
            log.warning("DXGI unavailable; using MSS", exc_info=True)

    def close(self) -> None:
        if self.camera is not None:
            self.camera.release()
            self.camera = None
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

    def grab(self) -> np.ndarray | None:
        if self.region is None:
            raise RuntimeError("Capture region is not set")
        if self.camera is not None:
            r = self.region
            if (
                0 <= r.left < r.left + r.width <= self.camera.width
                and 0 <= r.top < r.top + r.height <= self.camera.height
            ):
                try:
                    # DXGI returns None when no new desktop frame is available.
                    # Polling must not turn that into a missing skillcheck.
                    return self.camera.grab(
                        region=(r.left, r.top, r.left + r.width, r.top + r.height)
                    )
                except Exception:
                    log.warning("DXGI capture failed; using MSS", exc_info=True)
            else:
                log.info("Capture moved outside primary output; using MSS")
            self.camera.release()
            self.camera = None
            self.name = "MSS"
        return np.asarray(self.backend.grab(self.region.as_dict()))[:, :, :3]
