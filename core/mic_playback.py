"""Timing helpers for playing microphone segments back in sync.

Each segment file is named ``mikro_<startsecond>.<ext>``. During playback the
master timeline position determines which segment (if any) should be audible
and at what offset within that segment.
"""

from __future__ import annotations

import re
from typing import Optional

_SEG = re.compile(r"^mikro_(\d+)\.(?:wav|mp3|opus)$")


def parse_segment_start(filename: str) -> Optional[int]:
    m = _SEG.match(filename)
    return int(m.group(1)) if m else None


def segment_local_offset(start_ms: int, duration_ms: int, position_ms: int) -> Optional[int]:
    """Offset (ms) into the segment for the given master position, or None.

    Returns None when the master position is outside the segment's window. A
    ``duration_ms`` of 0 means "not yet known" — the segment is treated as
    active for any position at or after its start.
    """
    local = position_ms - start_ms
    if local < 0:
        return None
    if duration_ms > 0 and local >= duration_ms:
        return None
    return local
