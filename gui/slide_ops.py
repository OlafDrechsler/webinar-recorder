"""Shared slide-file operations for the player and the sort-out tool.

From a right-click on a slide (big image or film strip) both tools offer the same
actions: adjust its timestamp, move it aside (``_aussortiert``) or delete it.
Keeping the fiddly rename/collision handling here means both behave identically.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from core.i18n import tr
from gui.dialogs import ask_yes_no

_PREFIX = re.compile(r"^(\d+)(.*)$")


def fmt_seconds(total_s: int) -> str:
    total_s = max(0, total_s)
    return f"{total_s // 60:02d}:{total_s % 60:02d}"


def slide_second(name: str) -> int | None:
    """Recording-second encoded in the leading digits of a slide filename."""
    m = _PREFIX.match(name)
    return int(m.group(1)) if m else None


def rename_second(name: str, new_second: int) -> str:
    """Replace the leading second-prefix, keeping any suffix
    (``00050.png`` -> ``00080.png``; ``00050_edit_01.png`` -> ``00080_edit_01.png``)."""
    m = _PREFIX.match(name)
    if not m:
        return name
    return f"{new_second:05d}{m.group(2)}"


def safe_time_range(occupied: set[int], current: int, duration_s: int | None) -> tuple[int, int]:
    """The ``[lo, hi]`` seconds a slide at ``current`` may move to without crossing
    a neighbouring distinct second (so the order can never change). Always contains
    ``current``; ``lo == hi`` means there is no room."""
    prev = max((s for s in occupied if s < current), default=None)
    nxt = min((s for s in occupied if s > current), default=None)
    lo = prev + 1 if prev is not None else 0
    if nxt is not None:
        hi = nxt - 1
    else:
        hi = max(current, duration_s if duration_s else current + 600)
    return lo, hi


class TimeAdjustDialog(QDialog):
    """Pick a new second for a slide, limited to ``[lo, hi]``. The spin box defaults
    to the current second and shows the matching mm:ss live."""

    def __init__(self, parent, name: str, current: int, lo: int, hi: int, icon: QIcon | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("player.adjust_time"))
        if icon is not None:
            self.setWindowIcon(icon)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("time.current", name=name)))

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("time.new_time")))
        self._spin = QSpinBox()
        self._spin.setRange(lo, hi)
        self._spin.setValue(current)
        self._spin.setSuffix(" s")
        row.addWidget(self._spin)
        self._mmss = QLabel(fmt_seconds(current))
        self._mmss.setStyleSheet("color:#888;")
        row.addWidget(self._mmss)
        row.addStretch(1)
        lay.addLayout(row)

        rng = QLabel(tr("time.range", lo=f"{lo} s ({fmt_seconds(lo)})", hi=f"{hi} s ({fmt_seconds(hi)})"))
        rng.setStyleSheet("color:#888;")
        lay.addWidget(rng)

        self._spin.valueChanged.connect(lambda v: self._mmss.setText(fmt_seconds(v)))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def value(self) -> int:
        return self._spin.value()


def adjust_slide_time(parent, slides_dir: Path, name: str, occupied: set[int],
                      duration_s: int | None = None, icon: QIcon | None = None) -> str | None:
    """Show the adjust-time dialog for ``name`` and rename it within the safe gap.
    ``occupied`` is the set of distinct seconds already present in the folder.
    Returns the new filename, or None when nothing changed."""
    cur = slide_second(name)
    if cur is None:
        return None
    lo, hi = safe_time_range(occupied, cur, duration_s)
    # The range always contains the current second, so it is never empty — "no room"
    # is when it contains only that value (the neighbours are right next to it).
    if lo == hi:
        QMessageBox.information(parent, tr("player.adjust_time"), tr("time.no_room"))
        return None
    dlg = TimeAdjustDialog(parent, name, cur, lo, hi, icon)
    if dlg.exec() != QDialog.Accepted:
        return None
    new_second = dlg.value()
    if new_second == cur:
        return None
    new_name = rename_second(name, new_second)
    target = slides_dir / new_name
    if target.exists():
        QMessageBox.warning(parent, tr("player.adjust_time"), tr("time.collision"))
        return None
    try:
        (slides_dir / name).rename(target)
    except OSError:
        return None
    return new_name


def move_slide(slides_dir: Path, name: str) -> bool:
    """Move a slide to ``slides_dir/_aussortiert``. Returns True on success."""
    dest = slides_dir / "_aussortiert"
    dest.mkdir(exist_ok=True)
    try:
        shutil.move(str(slides_dir / name), str(dest / name))
        return True
    except OSError:
        return False


def delete_slide(parent, slides_dir: Path, name: str) -> bool:
    """Confirm, then permanently delete a slide. Returns True if it was deleted."""
    if not ask_yes_no(parent, tr("player.delete_title"), tr("player.delete_body", name=name)):
        return False
    try:
        (slides_dir / name).unlink()
    except OSError:
        pass
    return True
