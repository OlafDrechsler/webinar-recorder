"""Tracks the baseline frame used to decide whether a new screenshot is saved.

The baseline is always the most recently *auto-saved* frame. Manual annotated
saves are deliberately kept out of this state (step 7 of the highlight
workflow): they must never become the comparison baseline, otherwise the next
unchanged slide would be re-saved.
"""

from __future__ import annotations

import numpy as np

from core.change_detection import (
    DEFAULT_FRACTION_THRESHOLD,
    DEFAULT_PIXEL_THRESHOLD,
    frames_differ,
)


class CaptureState:
    def __init__(
        self,
        pixel_threshold: int = DEFAULT_PIXEL_THRESHOLD,
        fraction_threshold: float = DEFAULT_FRACTION_THRESHOLD,
    ) -> None:
        self._baseline: np.ndarray | None = None
        self._pixel_threshold = pixel_threshold
        self._fraction_threshold = fraction_threshold

    def consider(self, frame: np.ndarray) -> bool:
        """Return True and adopt ``frame`` as baseline if it differs enough."""
        if frames_differ(
            self._baseline,
            frame,
            self._pixel_threshold,
            self._fraction_threshold,
        ):
            self._baseline = frame.copy()
            return True
        return False

    def note_marked_save(self, frame: np.ndarray) -> None:
        """Record that a manual annotated frame was saved.

        Intentionally a no-op on the baseline — see module docstring.
        """
        # No state change by design.
        return None

    def reset(self) -> None:
        """Drop the baseline, e.g. after the capture region was resized."""
        self._baseline = None
