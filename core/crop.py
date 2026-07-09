"""Lossless batch-crop of slide PNGs.

Cropping a PNG only drops the pixels outside the kept rectangle and re-saves the
rest — PNG is lossless, so the remaining pixels are byte-for-byte the same image
data (no re-compression, no artefacts). Used by the sort-out tool to trim a
useless strip off every slide at once.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PIL import Image

# A crop box is (left, top, right, bottom) in pixels, right/bottom exclusive.
Box = tuple[int, int, int, int]


def clamp_box(box: Box, width: int, height: int) -> Box | None:
    """Clamp ``box`` to an image of the given size. Returns None if the result is
    empty (the box lies fully outside the image)."""
    left, top, right, bottom = box
    left = max(0, min(left, width))
    top = max(0, min(top, height))
    right = max(0, min(right, width))
    bottom = max(0, min(bottom, height))
    if right <= left or bottom <= top:
        return None
    return (left, top, right, bottom)


def crop_folder(folder: Path, box: Box, backup: bool = True, progress=None,
                names: set[str] | None = None) -> int:
    """Crop top-level PNGs in ``folder`` to ``box`` (reference pixels).

    ``names``, if given, restricts cropping to those filenames (e.g. a selected
    range); otherwise every PNG is cropped. ``box`` is clamped per image, so
    slides of an odd size are handled safely and an image already smaller than the
    box is left as-is. With ``backup`` the untouched original is copied to
    ``folder/_original`` first (existing backups are never overwritten, so
    re-cropping keeps the true original). Lossless. ``progress(done, total)`` is
    called as it goes. Returns the number cropped.
    """
    folder = Path(folder)
    paths = sorted(folder.glob("*.png"))
    if names is not None:
        paths = [p for p in paths if p.name in names]
    backup_dir = folder / "_original"
    total = len(paths)
    cropped_count = 0
    for i, path in enumerate(paths):
        if progress is not None:
            progress(i, total)
        try:
            with Image.open(path) as img:
                w, h = img.size
                cbox = clamp_box(box, w, h)
                if cbox is None or cbox == (0, 0, w, h):
                    continue  # nothing to trim off this image
                cropped = img.crop(cbox).copy()  # .copy() detaches from the file
        except OSError:
            continue
        try:
            st = path.stat()
        except OSError:
            st = None
        if backup:
            backup_dir.mkdir(exist_ok=True)
            dest = backup_dir / path.name
            if not dest.exists():  # keep the earliest original if cropped twice
                try:
                    shutil.copy2(str(path), str(dest))
                except OSError:
                    pass
        try:
            cropped.save(str(path))
        except OSError:
            continue
        cropped_count += 1
        if st is not None:  # keep the slide's original date, not "now"
            try:
                os.utime(path, (st.st_atime, st.st_mtime))
            except OSError:
                pass
    if progress is not None:
        progress(total, total)
    return cropped_count
