"""Screen-region capture using mss.

Returns frames as RGB numpy arrays so they can be fed straight into the
change-detection logic and saved with Pillow.

DPI note: Qt reports the selection rectangle in *logical* (DPI-scaled) pixels,
but mss grabs in *physical* pixels. On a display scaled to e.g. 150% the two
diverge, so the region selector converts its logical rectangle to physical
pixels via ``physical_region`` before handing it here. On a 100% display the
ratio is 1.0 and nothing changes.
"""

from __future__ import annotations

import numpy as np


class Region:
    __slots__ = ("left", "top", "width", "height")

    def __init__(self, left: int, top: int, width: int, height: int) -> None:
        self.left = int(left)
        self.top = int(top)
        self.width = int(width)
        self.height = int(height)

    def as_mss_dict(self) -> dict:
        return {
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Region):
            return NotImplemented
        return self.as_mss_dict() == other.as_mss_dict()

    def __repr__(self) -> str:
        return f"Region(left={self.left}, top={self.top}, width={self.width}, height={self.height})"


def physical_region(left, top, width, height, dpr: float) -> Region:
    """Convert a logical (Qt) rectangle to physical pixels for mss.

    ``dpr`` is the device-pixel ratio of the display (1.0 at 100%, 1.5 at 150%).
    Multiplying maps Qt's logical coordinates onto the true pixel grid mss uses.
    """
    return Region(
        round(left * dpr),
        round(top * dpr),
        round(width * dpr),
        round(height * dpr),
    )


class ScreenCapturer:
    """Grabs a fixed region. Create one per thread (mss is not thread-safe)."""

    def __init__(self) -> None:
        import mss

        self._sct = mss.mss()

    def grab(self, region: Region) -> np.ndarray:
        raw = self._sct.grab(region.as_mss_dict())
        # mss returns BGRA; convert to a contiguous RGB array.
        frame = np.frombuffer(raw.rgb, dtype=np.uint8)
        return frame.reshape((raw.height, raw.width, 3))

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapturer":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
