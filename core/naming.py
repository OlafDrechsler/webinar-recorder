"""Filename generation for saved slide frames.

Auto-saved frames are named by their second-offset from recording start
(``00137.png``) so playback can map a frame to a point in the audio track.
Manually annotated frames keep that second but get a running counter so
repeated highlights of the same moment never overwrite each other
(``00137_markiert_01.png``, ``00137_markiert_02.png``, ...).
"""

from __future__ import annotations

import re
from typing import Iterable

PAD = 5


def auto_frame_name(seconds: int) -> str:
    return f"{seconds:0{PAD}d}.png"


def marked_frame_name(seconds: int, existing: Iterable[str]) -> str:
    prefix = f"{seconds:0{PAD}d}"
    pattern = re.compile(rf"^{re.escape(prefix)}_markiert_(\d+)\.png$")
    highest = 0
    for name in existing:
        m = pattern.match(name)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}_markiert_{highest + 1:02d}.png"
