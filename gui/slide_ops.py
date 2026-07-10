"""Shared slide-file operations for the player and the sort-out tool.

From a right-click on a slide (big image or film strip) both tools offer the same
actions: adjust its timestamp, move it aside (``_aussortiert``) or delete it.
Keeping the fiddly rename/collision handling here means both behave identically.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from PySide6.QtGui import QIcon, QValidator
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from core.i18n import tr
from core.naming import marked_frame_name
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


class _GuardedSpinBox(QSpinBox):
    """Bounded to ``[lo, hi]`` for the arrows / normal use (sensible guardrails),
    but the user may TYPE a value beyond it (up to ``hard_max``) to force a reorder.
    ``chosen_value()`` returns what was actually entered, even outside the range."""

    def __init__(self, lo: int, hi: int, hard_max: int, value: int) -> None:
        super().__init__()
        self._lo, self._hi, self._hard_max = lo, hi, hard_max
        self.setRange(lo, hi)
        self.setValue(value)
        self._override: int | None = None  # a typed value outside [lo, hi]
        self.lineEdit().textEdited.connect(self._on_edited)

    def _on_edited(self, text: str) -> None:
        t = text.strip()
        self._override = int(t) if (t.isdigit() and not (self._lo <= int(t) <= self._hi)) else None

    def validate(self, text: str, pos: int):  # noqa: N802
        # Let the user keep typing an out-of-range (but valid) second instead of
        # clamping the keystrokes away.
        t = text.strip()
        if t == "":
            return (QValidator.Intermediate, text, pos)
        if t.isdigit() and 0 <= int(t) <= self._hard_max:
            return (QValidator.Acceptable, text, pos)
        return (QValidator.Invalid, text, pos)

    def chosen_value(self) -> int:
        return self._override if self._override is not None else self.value()


class TimeAdjustDialog(QDialog):
    """Pick a new second for a slide. The spin box guards to ``[lo, hi]`` (no
    reorder); typing a value beyond it is allowed and handled by the caller."""

    def __init__(self, parent, name: str, current: int, lo: int, hi: int,
                 hard_max: int, icon: QIcon | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("player.adjust_time"))
        if icon is not None:
            self.setWindowIcon(icon)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("time.current", name=name)))

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("time.new_time")))
        self._spin = _GuardedSpinBox(lo, hi, hard_max, current)
        row.addWidget(self._spin)
        self._mmss = QLabel(fmt_seconds(current))
        self._mmss.setStyleSheet("color:#888;")
        row.addWidget(self._mmss)
        row.addStretch(1)
        lay.addLayout(row)

        rng = QLabel(tr("time.range", lo=f"{lo} s ({fmt_seconds(lo)})", hi=f"{hi} s ({fmt_seconds(hi)})"))
        rng.setStyleSheet("color:#888;")
        lay.addWidget(rng)

        self._spin.valueChanged.connect(self._update_mmss)
        self._spin.lineEdit().textEdited.connect(self._update_mmss)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _update_mmss(self, *_a) -> None:
        self._mmss.setText(fmt_seconds(self._spin.chosen_value()))

    def value(self) -> int:
        return self._spin.chosen_value()


def adjust_slide_time(parent, slides_dir: Path, name: str, occupied: set[int],
                      duration_s: int | None = None, icon: QIcon | None = None) -> str | None:
    """Show the adjust-time dialog for ``name`` and rename it. Within the safe gap
    the change applies silently; a value outside it reorders the slides and is
    confirmed first (with a stronger warning when another slide already sits on
    that second). If the target filename is taken, the moved slide gets a suffix so
    both end up side by side. Returns the new filename or None."""
    cur = slide_second(name)
    if cur is None:
        return None
    lo, hi = safe_time_range(occupied, cur, duration_s)
    hard_max = duration_s if duration_s else 99999
    dlg = TimeAdjustDialog(parent, name, cur, lo, hi, hard_max, icon)
    if dlg.exec() != QDialog.Accepted:
        return None
    new_second = max(0, min(hard_max, dlg.value()))
    if new_second == cur:
        return None
    if not (lo <= new_second <= hi):  # outside the guardrails -> reorder, confirm
        occupied_by_other = new_second in occupied  # new_second != cur, so it's another slide
        body = tr("time.reorder_occupied_body") if occupied_by_other else tr("time.reorder_body")
        if not ask_yes_no(parent, tr("time.reorder_title"), body):
            return None
    src = slides_dir / name
    new_name = rename_second(name, new_second)
    target = slides_dir / new_name
    if target.exists() and target != src:
        # Another slide already has that exact filename — keep both side by side by
        # giving the moved slide a suffix (sorts right after the existing one).
        new_name = marked_frame_name(new_second, {p.name for p in slides_dir.glob("*.png")})
        target = slides_dir / new_name
    try:
        src.rename(target)
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
