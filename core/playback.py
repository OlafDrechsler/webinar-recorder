"""Pure helpers for the player: playback-speed steps and seek targets.

Kept free of Qt so the arithmetic can be unit-tested.
"""

from __future__ import annotations

SPEED_MIN_PCT = 50
SPEED_MAX_PCT = 200
SPEED_STEP_PCT = 10
SEEK_STEP_MS = 10_000  # 10 seconds for the double-click skip


def speed_percent_values() -> list[int]:
    """Selectable playback speeds in percent: 50, 60, … 200."""
    return list(range(SPEED_MIN_PCT, SPEED_MAX_PCT + 1, SPEED_STEP_PCT))


def seek_target(position_ms: int, delta_ms: int, duration_ms: int) -> int:
    """New position after skipping by ``delta_ms``, clamped to [0, duration]."""
    target = position_ms + delta_ms
    if target < 0:
        target = 0
    if duration_ms and target > duration_ms:
        target = duration_ms
    return target
