"""Post-recording slide deduplication with an ignorable speaker region.

The recorder saves a new screenshot whenever the (downscaled) frame changes. When
a speaker is overlaid on the slides, the speaker's constant motion makes nearly
identical slides be saved over and over. This module lets a region (the speaker)
be *ignored* during comparison, so only real slide changes count.

Pure logic (numpy + PIL only, no GUI): build a compare-mask from rectangles /
ellipses, decide whether two frames differ outside the ignored area, and plan
which files are duplicates. The GUI (``gui/sort_out.py``) draws the regions and
moves/deletes the planned files.

Comparison mirrors the live recorder: both frames are shrunk to ~320 px wide
(averaging out video-compression noise), then compared per pixel. Only pixels
inside the compare-mask are counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

import numpy as np
from PIL import Image

DEFAULT_PIXEL_THRESHOLD = 12
DEFAULT_FRACTION_THRESHOLD = 0.005
DEFAULT_COMPARE_WIDTH = 320

# Region shapes.
RECT = "rect"
ELLIPSE = "ellipse"

# Mask modes.
IGNORE = "ignore"    # compare everything EXCEPT the regions (regions = speaker)
COMPARE = "compare"  # compare ONLY the regions (regions = slide area)


@dataclass
class Region:
    shape: str          # RECT or ELLIPSE
    left: int
    top: int
    width: int
    height: int


def _fill_region(mask: np.ndarray, region: Region, value: bool) -> None:
    """Set the pixels of ``region`` in ``mask`` to ``value`` (clipped to bounds)."""
    height, width = mask.shape
    x0 = max(0, int(region.left))
    y0 = max(0, int(region.top))
    x1 = min(width, int(region.left) + int(region.width))
    y1 = min(height, int(region.top) + int(region.height))
    if x1 <= x0 or y1 <= y0:
        return
    if region.shape == ELLIPSE:
        cx = region.left + region.width / 2.0
        cy = region.top + region.height / 2.0
        rx = max(region.width / 2.0, 1e-6)
        ry = max(region.height / 2.0, 1e-6)
        ys = np.arange(y0, y1)[:, None]
        xs = np.arange(x0, x1)[None, :]
        inside = ((xs - cx) / rx) ** 2 + ((ys - cy) / ry) ** 2 <= 1.0
        mask[y0:y1, x0:x1][inside] = value
    else:  # RECT
        mask[y0:y1, x0:x1] = value


def build_compare_mask(width: int, height: int, regions: Sequence[Region], mode: str) -> np.ndarray:
    """Boolean (height, width) mask: True where pixels are compared.

    IGNORE mode: compare everything except the regions (speaker areas).
    COMPARE mode: compare only the regions; with no regions, compare everything.
    """
    if mode == COMPARE:
        if not regions:
            return np.ones((height, width), dtype=bool)
        mask = np.zeros((height, width), dtype=bool)
        for r in regions:
            _fill_region(mask, r, True)
        return mask
    # IGNORE (default)
    mask = np.ones((height, width), dtype=bool)
    for r in regions:
        _fill_region(mask, r, False)
    return mask


def _target_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    if width <= max_width:
        return width, height
    scale = max_width / width
    return max_width, max(1, round(height * scale))


def _downscale_rgb(frame: np.ndarray, tw: int, th: int) -> np.ndarray:
    if (frame.shape[1], frame.shape[0]) == (tw, th):
        return frame
    return np.asarray(Image.fromarray(frame).resize((tw, th), Image.BILINEAR))


def _downscale_mask(mask: np.ndarray, tw: int, th: int) -> np.ndarray:
    if (mask.shape[1], mask.shape[0]) == (tw, th):
        return mask
    img = Image.fromarray((mask.astype(np.uint8) * 255)).resize((tw, th), Image.NEAREST)
    return np.asarray(img) > 127


def masked_changed_fraction(
    prev: np.ndarray,
    curr: np.ndarray,
    compare_mask: np.ndarray,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
    max_width: int = DEFAULT_COMPARE_WIDTH,
) -> float:
    """Fraction of compared pixels that differ by more than ``pixel_threshold``."""
    h, w = prev.shape[:2]
    tw, th = _target_size(w, h, max_width)
    p = _downscale_rgb(prev, tw, th).astype(np.int16)
    c = _downscale_rgb(curr, tw, th).astype(np.int16)
    m = _downscale_mask(compare_mask, tw, th)
    diff = np.abs(p - c).max(axis=2)
    changed = diff > pixel_threshold
    denom = int(m.sum())
    if denom == 0:
        return 0.0
    return float((changed & m).sum()) / denom


def masked_frames_differ(
    prev: Optional[np.ndarray],
    curr: Optional[np.ndarray],
    compare_mask: np.ndarray,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
    fraction_threshold: float = DEFAULT_FRACTION_THRESHOLD,
    max_width: int = DEFAULT_COMPARE_WIDTH,
) -> bool:
    """True if the frames differ (outside the ignored area) enough to be kept."""
    if prev is None or curr is None:
        return True
    if prev.shape != curr.shape:
        return True
    frac = masked_changed_fraction(prev, curr, compare_mask, pixel_threshold, max_width)
    return frac > fraction_threshold


_LEADING_NUM = re.compile(r"^(\d+)")


def numeric_key(path) -> int:
    """Sort key from the leading digits of a filename (e.g. 00012.png -> 12)."""
    m = _LEADING_NUM.match(Path(path).name)
    return int(m.group(1)) if m else -1


def plan_deletions(
    paths: Sequence[Path],
    load: Callable[[Path], np.ndarray],
    compare_mask: np.ndarray,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
    fraction_threshold: float = DEFAULT_FRACTION_THRESHOLD,
    max_width: int = DEFAULT_COMPARE_WIDTH,
    progress: Optional[Callable[[int, int], None]] = None,
) -> list[Path]:
    """Return the paths that are duplicates of an earlier kept frame.

    ``paths`` must already be in ascending order. The baseline is the last KEPT
    frame, so within a run of identical slides the first (lowest-numbered) one is
    always kept and the later ones are returned for removal.
    """
    baseline: Optional[np.ndarray] = None
    removals: list[Path] = []
    total = len(paths)
    for i, path in enumerate(paths):
        frame = load(path)
        if baseline is None:
            baseline = frame
        elif masked_frames_differ(
            baseline, frame, compare_mask, pixel_threshold, fraction_threshold, max_width
        ):
            baseline = frame  # real change -> keep, becomes new baseline
        else:
            removals.append(path)  # duplicate -> remove, baseline unchanged
        if progress is not None:
            progress(i + 1, total)
    return removals
