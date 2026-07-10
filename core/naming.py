"""Filename generation for saved slide frames.

Auto-saved frames are named by their second-offset from recording start
(``00137.png``) so playback can map a frame to a point in the audio track.
Manually edited frames keep that second but get a running counter so repeated
edits of the same moment never overwrite each other (``00137_edit_01.png``,
``00137_edit_02.png``, ...). Legacy ``_markiert_`` files still count toward the
counter so old recordings don't collide.
"""

from __future__ import annotations

import re
from typing import Iterable

PAD = 5


def auto_frame_name(seconds: int) -> str:
    return f"{seconds:0{PAD}d}.png"


def marked_frame_name(seconds: int, existing: Iterable[str]) -> str:
    prefix = f"{seconds:0{PAD}d}"
    # New edits use "_edit_"; legacy "_markiert_" files also count so the running
    # counter never collides with already-saved annotations.
    pattern = re.compile(rf"^{re.escape(prefix)}_(?:markiert|edit)_(\d+)\.png$")
    highest = 0
    for name in existing:
        m = pattern.match(name)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}_edit_{highest + 1:02d}.png"


def moved_frame_name(seconds: int, existing: Iterable[str]) -> str:
    """Name for a slide moved onto an already-occupied second: keep the second and
    add a running counter (``00010_01.png``, ``00010_02.png``, ...) so it lands
    right after the existing slide(s) there instead of overwriting them. A third
    scheme next to the auto (``NNNNN.png``) and annotated (``NNNNN_edit_NN.png``)
    names."""
    prefix = f"{seconds:0{PAD}d}"
    pattern = re.compile(rf"^{re.escape(prefix)}_(\d+)\.png$")
    highest = 0
    for name in existing:
        m = pattern.match(name)
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}_{highest + 1:02d}.png"
