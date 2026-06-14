"""Maps a playback position (seconds) to the slide that should be shown.

The auto-saved frames (``NNNNN.png``) form the slideshow timeline; each is
named by its second-offset from recording start. Annotated frames
(``..._markiert_NN.png``) are deliberately excluded — they are user-saved
extras, browsable in the folder but not part of automatic advancing.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from typing import Iterable

_AUTO = re.compile(r"^(\d+)\.png$")


def parse_seconds(filename: str) -> int | None:
    m = _AUTO.match(filename)
    return int(m.group(1)) if m else None


def build_timeline(filenames: Iterable[str]) -> list[tuple[int, str]]:
    entries = []
    for name in filenames:
        sec = parse_seconds(name)
        if sec is not None:
            entries.append((sec, name))
    entries.sort()
    return entries


def slide_for_second(timeline: list[tuple[int, str]], second: int) -> str | None:
    """Return the filename of the latest slide whose second is <= ``second``."""
    if not timeline:
        return None
    seconds = [s for s, _ in timeline]
    idx = bisect_right(seconds, second) - 1
    if idx < 0:
        return None
    return timeline[idx][1]
