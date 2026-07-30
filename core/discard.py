"""Discard the tail OR the beginning of a recording at a chosen second.

Tail (``discard_from_second``): cut the system track to ``[0, t]`` and delete
every slide and mic segment at or after second ``t`` (e.g. the recording was
stopped late).

Beginning (``discard_before_second``): cut the system track's head, delete
everything before the slide visible at ``t`` and renumber the survivors so the
recording restarts at 0 (e.g. a useless intro). A mic segment spanning ``t`` is
trimmed at its head and kept.

Used by the player, sort-out and crop tools. Pure file logic (no Qt) so it can be
unit-tested.
"""

from __future__ import annotations

import re
from pathlib import Path

from core.mic_playback import parse_segment_start
from io_adapters.encode import audio_duration, trim_audio, trim_audio_start

_SECOND = re.compile(r"^(\d+)")


def _second(name: str) -> int | None:
    m = _SECOND.match(name)
    return int(m.group(1)) if m else None


def _rename_second(name: str, new_second: int) -> str:
    """Replace the leading second-prefix, keeping any suffix (e.g.
    ``00040_edit_01.png`` -> ``00012_edit_01.png``). Local copy to keep this module
    Qt-free (``gui.slide_ops.rename_second`` imports Qt)."""
    m = re.match(r"^(\d+)(.*)$", name)
    if not m:
        return name
    width = len(m.group(1))
    return f"{new_second:0{width}d}{m.group(2)}"


def _system_track(session_dir: Path) -> Path | None:
    for ext in (".mp3", ".wav", ".opus"):
        track = session_dir / f"system{ext}"
        if track.exists():
            return track
    return None


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


def _rename_mic(path: Path, new_start: int) -> None:
    m = re.match(r"^mikro_(\d+)(\..+)$", path.name)
    if not m:
        return
    width = len(m.group(1))
    new_name = f"mikro_{new_start:0{width}d}{m.group(2)}"
    if new_name != path.name:
        try:
            path.rename(path.with_name(new_name))
        except OSError:
            pass


def _mic_fully_before(path: Path, start: int, t_seconds: int) -> bool:
    """True if the segment ends at or before ``t`` (so it is dropped entirely). A
    segment whose length can't be measured is treated as fully-before (dropped
    rather than kept as an empty file)."""
    if start >= t_seconds:
        return False
    dur = audio_duration(path)
    if dur is None:
        return True
    return (start + dur) <= t_seconds


def count_before_second(folien_dir: Path, mic_dir: Path, t_seconds: int) -> tuple[int, int]:
    """(slides, mic segments) removed by discarding everything BEFORE second ``t`` —
    for the confirmation. Slides before the one visible at ``t`` are dropped; mic
    segments that end at or before ``t`` are dropped (a spanning one is kept)."""
    folien_dir = Path(folien_dir)
    secs = [s for p in folien_dir.glob("*.png") if (s := _second(p.name)) is not None]
    base = max((s for s in secs if s <= t_seconds), default=None)
    slides = 0 if base is None else sum(1 for s in secs if s < base)
    mics = 0
    mic_dir = Path(mic_dir)
    if mic_dir.is_dir():
        for p in mic_dir.glob("mikro_*"):
            start = parse_segment_start(p.name)
            if start is not None and _mic_fully_before(p, start, t_seconds):
                mics += 1
    return slides, mics


def discard_before_second(session_dir: Path, folien_dir: Path, t_seconds: int) -> tuple[int, int]:
    """Discard everything BEFORE second ``t``: trim the system track's head, delete
    slides/mic segments before the cut and renumber the survivors so the recording
    now starts at 0. Returns (slides_removed, mic_segments_removed).

    The slide visible at ``t`` (the last one at or before it) becomes second 0;
    slides after ``t`` shift down by ``t``. A mic segment spanning ``t`` is trimmed
    at its head and becomes segment 0."""
    session_dir = Path(session_dir)
    folien_dir = Path(folien_dir)

    track = _system_track(session_dir)
    if track is not None:
        trim_audio_start(track, t_seconds)

    frames = [(s, p) for p in folien_dir.glob("*.png") if (s := _second(p.name)) is not None]
    base = max((s for s, _ in frames if s <= t_seconds), default=None)
    slides_removed = 0
    survivors: list[tuple[int, Path]] = []
    for s, p in frames:
        if base is not None and s < base:
            try:
                p.unlink()
                slides_removed += 1
            except OSError:
                pass
        else:
            survivors.append((max(0, s - t_seconds), p))
    # Rename ascending by current name (== ascending second) so each smaller target
    # never clobbers a source still waiting to be renamed.
    for new_s, p in sorted(survivors, key=lambda it: it[1].name):
        new_name = _rename_second(p.name, new_s)
        if new_name != p.name:
            try:
                p.rename(p.with_name(new_name))
            except OSError:
                pass

    mics_removed = 0
    mic_dir = session_dir / "mikro"
    if mic_dir.is_dir():
        segs = [(start, p) for p in mic_dir.glob("mikro_*")
                if (start := parse_segment_start(p.name)) is not None]
        for start, p in sorted(segs, key=lambda it: it[0]):
            if start >= t_seconds:
                _rename_mic(p, start - t_seconds)
            elif _mic_fully_before(p, start, t_seconds):
                try:
                    p.unlink()
                    mics_removed += 1
                except OSError:
                    pass
            else:  # spans the cut: trim its head, it becomes segment 0
                trim_audio_start(p, t_seconds - start)
                _rename_mic(p, 0)
    return slides_removed, mics_removed
