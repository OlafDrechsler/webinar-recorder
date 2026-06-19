"""Generate the WebinarOD app icon (assets/icon.png + assets/icon.ico).

Motif: a small stack of slide cards with a colourful play badge — "slides that
play back". Drawn with Pillow (already a dependency), no SVG renderer needed.
Run:  python tools/make_icon.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
S = 256  # master size


def _vgradient(size, top, bottom):
    """Vertical gradient RGBA image."""
    h = w = size
    t = np.linspace(0.0, 1.0, h)[:, None]
    top = np.array(top, dtype=float)
    bottom = np.array(bottom, dtype=float)
    rows = (top[None, :] * (1 - t) + bottom[None, :] * t)
    arr = np.repeat(rows[:, None, :], w, axis=1).astype(np.uint8)
    alpha = np.full((h, w, 1), 255, np.uint8)
    return Image.fromarray(np.concatenate([arr, alpha], axis=2), "RGBA")


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius, fill=255)
    return m


def build_master() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded tile with a deep violet->navy gradient background.
    tile = _vgradient(S, (76, 46, 131), (26, 26, 48))
    img.paste(tile, (0, 0), _rounded_mask(S, 56))

    draw = ImageDraw.Draw(img)

    # Stack of three slide cards, offset diagonally (back to front).
    card_w, card_h, rad = 120, 92, 14
    base_x, base_y = 44, 50
    offsets = [(26, -26), (13, -7), (0, 12)]
    shades = [(210, 214, 230), (232, 235, 246), (255, 255, 255)]
    for (dx, dy), fill in zip(offsets, shades):
        x0, y0 = base_x + dx, base_y + dy
        x1, y1 = x0 + card_w, y0 + card_h
        draw.rounded_rectangle([x0, y0, x1, y1], rad, fill=fill)
        # a couple of "text" lines on the front-most card
        if fill == (255, 255, 255):
            draw.rounded_rectangle([x0 + 12, y0 + 16, x1 - 40, y0 + 24], 4, fill=(120, 130, 150))
            draw.rounded_rectangle([x0 + 12, y0 + 36, x1 - 22, y0 + 44], 4, fill=(180, 188, 205))
            draw.rounded_rectangle([x0 + 12, y0 + 56, x1 - 60, y0 + 64], 4, fill=(180, 188, 205))

    # Play badge (orange->pink gradient circle with white triangle), bottom-right.
    bd = 96
    badge = _vgradient(bd, (255, 138, 0), (255, 46, 116))
    cmask = Image.new("L", (bd, bd), 0)
    ImageDraw.Draw(cmask).ellipse([0, 0, bd - 1, bd - 1], fill=255)
    bx, by = S - bd - 18, S - bd - 18
    img.paste(badge, (bx, by), cmask)
    cx, cy = bx + bd / 2, by + bd / 2
    tri = [(cx - 16, cy - 24), (cx - 16, cy + 24), (cx + 26, cy)]
    ImageDraw.Draw(img).polygon(tri, fill=(255, 255, 255, 255))
    return img


def main() -> int:
    ASSETS.mkdir(exist_ok=True)
    master = build_master()
    master.save(ASSETS / "icon.png")
    sizes = [16, 24, 32, 48, 64, 128, 256]
    master.save(ASSETS / "icon.ico", sizes=[(s, s) for s in sizes])
    print("wrote", ASSETS / "icon.png", "and", ASSETS / "icon.ico")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
