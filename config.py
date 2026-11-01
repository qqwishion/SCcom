from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    capture_hz: int = 240
    # Additional frame-age allowance used only to reject stale overlaps.
    input_lead_ms: float = 0.0
    key_hold_ms: float = 12.0
    send_input: bool = True
    missing_reset_s: float = 0.18
    min_radius: int = 35
    max_radius: int = 130
    moonwalk_interval_ms: float = 53.0
    moonwalk_gap_ms: float = 10.0
    moonwalk_hold_vk: int = 0x14  # Caps Lock (held state, not toggle state)


CONFIG = Config()
