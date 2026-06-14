"""Pixel-based change detection between two captured frames.

Webinar slides are usually shared as a re-encoded video stream, so even a
static slide produces per-pixel compression jitter from frame to frame. To
avoid saving a flood of near-identical frames, both images are downscaled to a
small width before comparison: downscaling averages the scattered noise away
(it collapses to ~0) while real slide changes (new text, new layout) remain
clearly visible. Measured on real recordings, noise pairs drop to 0.0000 and
genuine changes stay at >= 0.16, leaving a wide, safe gap.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

# A pixel counts as "changed" only if it shifts by more than this many levels.
DEFAULT_PIXEL_THRESHOLD = 12
# The (downscaled) frame counts as changed if more than this fraction changed.
DEFAULT_FRACTION_THRESHOLD = 0.005  # 0.5 %
# Width the frames are shrunk to before comparison (only shrinks, never grows).
DEFAULT_COMPARE_WIDTH = 320


def _downscaled(frame: np.ndarray, max_width: int) -> np.ndarray:
    h, w = frame.shape[0], frame.shape[1]
    if w <= max_width:
        return frame
    new_h = max(1, round(h * max_width / w))
    img = Image.fromarray(frame).resize((max_width, new_h), Image.BILINEAR)
    return np.asarray(img)


def frames_differ(
    prev: np.ndarray,
    curr: np.ndarray,
    pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
    fraction_threshold: float = DEFAULT_FRACTION_THRESHOLD,
    max_width: int = DEFAULT_COMPARE_WIDTH,
) -> bool:
    """Return True if ``curr`` differs meaningfully from ``prev``.

    Frames of differing shape always count as changed: after a region resize
    the dimensions no longer line up, so the caller must reset its baseline.
    """
    if prev is None:
        return True
    if prev.shape != curr.shape:
        return True

    a = _downscaled(prev, max_width).astype(np.int16)
    b = _downscaled(curr, max_width).astype(np.int16)

    diff = np.abs(b - a)
    if diff.ndim == 3:
        # Collapse colour channels: a pixel changed if any channel moved enough.
        diff = diff.max(axis=2)

    changed_pixels = int(np.count_nonzero(diff > pixel_threshold))
    total_pixels = diff.shape[0] * diff.shape[1]
    if total_pixels == 0:
        return False
    return (changed_pixels / total_pixels) > fraction_threshold
