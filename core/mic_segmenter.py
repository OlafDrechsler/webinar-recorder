"""Voice-activity segmentation for the microphone.

Instead of recording one long (mostly silent) mic track, the mic is split into
segments that exist only while there is something to hear. A segment opens when
the level crosses a threshold (or the user forces it via manual override) and
closes after a "hangover" of continuous silence (default 10 s). Each segment is
tagged with the second-offset at which it started, so playback can drop it back
onto the timeline in sync.

This class is pure logic (no audio I/O): feed it a level and a timestamp, it
tells you when to open and close segment files.
"""

from __future__ import annotations

from typing import Optional, Tuple

Event = Tuple[str, int]  # ("start", start_sec) or ("stop", start_sec)


class MicSegmenter:
    def __init__(self, threshold: float, hangover_seconds: float = 10.0) -> None:
        self.threshold = threshold
        self.hangover = hangover_seconds
        self._active = False
        self._start: Optional[int] = None
        self._last_loud: float = 0.0

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def current_start(self) -> Optional[int]:
        return self._start

    def update(self, level: float, now: float, override: bool = False) -> Optional[Event]:
        loud = override or level > self.threshold

        if loud:
            self._last_loud = now
            if not self._active:
                self._active = True
                self._start = int(now)
                return ("start", self._start)
            return None

        # quiet and not overridden
        if self._active and (now - self._last_loud) >= self.hangover:
            start = self._start
            self._active = False
            self._start = None
            return ("stop", start)
        return None

    def finalize(self) -> Optional[Event]:
        """Close an open segment when recording ends. Returns the stop event."""
        if self._active:
            start = self._start
            self._active = False
            self._start = None
            return ("stop", start)
        return None
