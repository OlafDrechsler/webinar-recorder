"""Discard the tail of a recording from a chosen second onward.

Cuts the system track to ``[0, t]`` and deletes every slide and microphone
segment at or after second ``t`` — used by the sort-out and crop tools to drop a
useless tail (e.g. when the recording was stopped late). Pure file logic (no Qt)
so it can be unit-tested.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.mic_playback import parse_segment_start
from io_adapters.encode import trim_audio

_SECOND = re.compile(r"^(\d+)")


def _second(name: str) -> int | None:
    m = _SECOND.match(name)
    return int(m.group(1)) if m else None


def count_from_second(folien_dir: Path, mic_dir: Path, t_seconds: int) -> tuple[int, int]:
    """(slides, mic segments) at or after second ``t`` — for the confirmation."""
    folien_dir = Path(folien_dir)
    slides = sum(1 for p in folien_dir.glob("*.png")
                 if (_second(p.name) or -1) >= t_seconds)
    mics = 0
    mic_dir = Path(mic_dir)
    if mic_dir.is_dir():
        mics = sum(1 for p in mic_dir.glob("mikro_*")
                   if (parse_segment_start(p.name) or -1) >= t_seconds)
    return slides, mics


def discard_from_second(session_dir: Path, folien_dir: Path, t_seconds: int) -> tuple[int, int]:
    """Trim the system track to ``[0, t]`` and delete slides + mic segments at or
    after second ``t``. Returns (slides_removed, mic_segments_removed)."""
    session_dir = Path(session_dir)
    folien_dir = Path(folien_dir)

    for ext in (".mp3", ".wav", ".opus"):  # trim whichever system track exists
        track = session_dir / f"system{ext}"
        if track.exists():
            trim_audio(track, t_seconds)
            break

    slides = 0
    for p in folien_dir.glob("*.png"):
        if (_second(p.name) or -1) >= t_seconds:
            try:
                p.unlink()
                slides += 1
            except OSError:
                pass

    mics = 0
    mic_dir = session_dir / "mikro"
    if mic_dir.is_dir():
        for p in mic_dir.glob("mikro_*"):
            start = parse_segment_start(p.name)
            if start is not None and start >= t_seconds:
                try:
                    p.unlink()
                    mics += 1
                except OSError:
                    pass
    return slides, mics
