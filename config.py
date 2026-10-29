from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    capture_hz: int = 180
    # Additional frame-age allowance used only to reject stale overlaps.
    input_lead_ms: float = 0.0
    key_hold_ms: float = 12.0
    send_input: bool = True
    missing_reset_s: float = 0.18
    min_radius: int = 35
    max_radius: int = 130


CONFIG = Config()
