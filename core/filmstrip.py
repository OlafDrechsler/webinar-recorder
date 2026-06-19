"""Ordered list of slide frames for the player's film strip, and the windowing
maths for showing them centred on the current frame.

Pure logic (no Qt) so it can be unit-tested. The strip includes the auto-saved
slides (``NNNNN.png``) AND the annotated frames (``NNNNN_markiert_NN.png``), each
placed at its second-offset. ``visible_slots`` decides which frames are shown in
a fixed number of slots with the current frame in the middle and empty slots at
the edges when there aren't enough frames on one side.
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple, Optional

_AUTO = re.compile(r"^(\d+)\.png$", re.IGNORECASE)
# Annotated frames: new "_edit_" and legacy "_markiert_".
_MARKED = re.compile(r"^(\d+)_(?:markiert|edit)_\d+\.png$", re.IGNORECASE)


class Frame(NamedTuple):
    second: int
    name: str
    marked: bool


def _parse(name: str) -> Optional[Frame]:
    m = _AUTO.match(name)
    if m:
        return Frame(int(m.group(1)), name, False)
    m = _MARKED.match(name)
    if m:
        return Frame(int(m.group(1)), name, True)
    return None


def build_filmstrip(filenames: Iterable[str]) -> list[Frame]:
    """All slide frames (auto + annotated), sorted by second then filename.

    For the same second the auto frame sorts before its ``_markiert_`` variants
    because '.' (0x2E) is below '_' (0x5F).
    """
    frames = [f for f in (_parse(n) for n in filenames) if f is not None]
    frames.sort(key=lambda f: (f.second, f.name))
    return frames


def visible_slots(total: int, current: int, slots: int) -> list[Optional[int]]:
    """Indices to show in ``slots`` cells with ``current`` centred.

    Cells that would fall before the first or after the last frame are ``None``
    (empty edge). ``slots`` should be odd so there is a true middle cell.
    """
    half = slots // 2
    result: list[Optional[int]] = []
    for offset in range(-half, slots - half):
        idx = current + offset
        result.append(idx if 0 <= idx < total else None)
    return result
