"""Loudness matching between the system track and the microphone segments.

After recording, the two sources often sit at very different volumes (a quiet
speaker vs. loud shared webinar audio). To make playback comfortable we measure
each source's loudness with FFmpeg and apply a single gain per source so both
reach a common target — no manual sliders needed.

Loudness is measured as EBU R128 *integrated loudness* (LUFS), which gates out
silence. That matters because the system track now contains the real silent
stretches (see the keepalive in io_adapters/audio.py); a plain mean would be
dragged down by that silence and over-boost the track. The true-peak (dBTP) is
used to cap the gain so normalisation never introduces clipping.

This module is pure logic (no FFmpeg): given a measured loudness and true peak it
computes a clip-safe gain in dB. Measuring and applying live in
``io_adapters/encode.py`` (``measure_loudness`` + ``transcode_to_mp3(gain_db=...)``)
and are wired together in ``app.py`` after recording.

Why one gain for all mic segments: normalising each short segment on its own
would make a quiet "mhm" as loud as an emphatic sentence. Measuring the segments
together and applying the same gain keeps the natural dynamics between them while
still matching their overall loudness to the system track.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

# Target integrated loudness (LUFS) both sources are nudged towards. -16 LUFS is
# a common, comfortable target for speech/streaming and leaves true-peak headroom.
DEFAULT_TARGET_DB = -16.0
# After gain, the true peak must stay at or below this (anti-clipping margin, dBTP).
PEAK_CEILING_DB = -1.0


def compute_gain_db(
    loudness_db: Optional[float],
    peak_db: Optional[float] = None,
    target_db: float = DEFAULT_TARGET_DB,
    ceiling_db: float = PEAK_CEILING_DB,
) -> float:
    """Gain (dB) to move ``loudness_db`` (LUFS) to ``target_db``, capped so the
    true peak ``peak_db`` (dBTP) stays at or below ``ceiling_db``.

    Returns 0.0 when ``loudness_db`` is missing (nothing measurable / silent
    file), so an unmeasurable track is left untouched rather than wrongly
    amplified.
    """
    if loudness_db is None:
        return 0.0
    gain = target_db - loudness_db
    if peak_db is not None:
        max_gain = ceiling_db - peak_db
        if gain > max_gain:
            gain = max_gain
    return gain


def aggregate_mean_db(values: Sequence[Optional[float]]) -> Optional[float]:
    """Combine several segment loudness values (LUFS) into one representative one.

    Averaging is done in the linear (power) domain (dB -> linear -> mean -> dB) so
    a few loud segments aren't diluted the way a plain arithmetic average would.
    Returns None if there is nothing measurable.
    """
    measured = [v for v in values if v is not None]
    if not measured:
        return None
    powers = [10 ** (v / 10.0) for v in measured]
    avg = sum(powers) / len(measured)
    return 10.0 * math.log10(avg) if avg > 0 else None
