"""Software mute for the microphone track.

The microphone is captured continuously so it stays perfectly aligned with the
system-audio timeline. When the user has the mic toggled off, the chunk is
replaced by silence of the same shape rather than dropped — preserving sync.
"""

from __future__ import annotations

import numpy as np


def gate_mic_chunk(chunk: np.ndarray, enabled: bool) -> np.ndarray:
    if enabled:
        return chunk
    return np.zeros_like(chunk)
