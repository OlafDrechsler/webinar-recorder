"""Crop tool ("Folien zuschneiden") — its own hub window.

Layout like the sort-out tool: folder picker, big reference image, film strip,
and a bottom row. You drag the rectangle to KEEP directly on the big image (the
part being trimmed is dimmed as a preview); the crop is the same for every slide,
so it stays put while you browse to check it. Start applies it to all slides
losslessly (see core.crop). A toggle in the Start row chooses whether the
untouched originals are kept in ``_original`` or overwritten.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressDialog,
    QPushButton,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.crop import Box, crop_folder
from core.discard import count_from_second, discard_from_second
from core.i18n import tr
from core.settings import get_data_dir, get_last_session, set_last_session
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_yes_no
from gui.selection import next_selection
from gui.slide_ops import delete_slide, fmt_seconds, move_slide, slide_second
from gui.sort_out import (
    SortFilmstrip,
    frame_to_qpixmap,
    load_frame,
    slide_frames,
    webinar_dir,
    webinar_name,
)


class CropCanvas(QWidget):
    """Shows a slide scaled to fit and lets the user drag one keep-rectangle. The
    area outside it is dimmed as a live preview. The rectangle persists across
    image changes (same crop for every slide)."""

    box_changed = Signal()
    context_requested = Signal()  # right-click -> range menu

    def __init__(self) -> None:
        super().__init__()
        self._pix: QPixmap | None = None
        self._box: list[float] | None = None  # [l, t, r, b] in image pixels
        self._drag_from: tuple[float, float] | None = None
        self.setMinimumSize(480, 320)

    def set_image(self, pix: QPixmap) -> None:
        """Swap the shown image but keep the drawn rectangle (browse across slides)."""
        self._pix = pix
        self.update()

    def reset(self) -> None:
        self._box = None
        self.update()
        self.box_changed.emit()

    def keep_box(self) -> Box | None:
        """The kept rectangle in image pixels, or None when it is the full image
        (nothing to crop) or nothing was drawn yet."""
        if self._pix is None or self._box is None:
            return None
        l, t, r, b = (int(round(v)) for v in self._box)
        if l <= 0 and t <= 0 and r >= self._pix.width() and b >= self._pix.height():
            return None
        return (l, t, r, b)

    # ----- geometry: widget <-> image pixels -----
    def _disp(self):
        pw, ph = self._pix.width(), self._pix.height()
        scale = min(self.width() / pw, self.height() / ph)
        ox = (self.width() - pw * scale) / 2
        oy = (self.height() - ph * scale) / 2
        return ox, oy, scale

    def _to_image(self, x: float, y: float) -> tuple[float, float]:
        ox, oy, scale = self._disp()
        ix = max(0, min(self._pix.width(), (x - ox) / scale))
        iy = max(0, min(self._pix.height(), (y - oy) / scale))
        return ix, iy

    def _img_to_widget(self, l, t, r, b) -> QRect:
        ox, oy, scale = self._disp()
        return QRect(int(ox + l * scale), int(oy + t * scale),
                     int((r - l) * scale), int((b - t) * scale))

    # ----- mouse -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self.context_requested.emit()
            return
        if self._pix is None:
            return
        self._drag_from = self._to_image(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pix is None or self._drag_from is None:
            return
        x1, y1 = self._drag_from
        x2, y2 = self._to_image(event.position().x(), event.position().y())
        self._box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
        self.update()
        self.box_changed.emit()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_from = None
        # A click without a real drag means "no crop".
        if self._box is not None and (self._box[2] - self._box[0] < 2 or self._box[3] - self._box[1] < 2):
            self._box = None
            self.update()
            self.box_changed.emit()

    # ----- paint -----
    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self._pix is None:
            return
        ox, oy, scale = self._disp()
        target = QRect(int(ox), int(oy), int(self._pix.width() * scale), int(self._pix.height() * scale))
        p.drawPixmap(target, self._pix)
        if self._box is None:
            return
        keep = self._img_to_widget(*self._box)
        shade = QColor(0, 0, 0, 140)  # dim the part being cropped away
        p.fillRect(QRect(target.left(), target.top(), target.width(), keep.top() - target.top()), shade)
        p.fillRect(QRect(target.left(), keep.bottom(), target.width(), target.bottom() - keep.bottom()), shade)
        p.fillRect(QRect(target.left(), keep.top(), keep.left() - target.left(), keep.height()), shade)
        p.fillRect(QRect(keep.right(), keep.top(), target.right() - keep.right(), keep.height()), shade)
        p.setPen(QPen(QColor(45, 166, 255), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(keep)


class CropWindow(QWidget):
    def __init__(self, folder: Path | None = None) -> None:
        super().__init__()
        self.setWindowIcon(app_icon())
        self.setWindowTitle(f"{APP_NAME} – {tr('hub.crop')}")
        self._folder: Path | None = None
        self._paths: list[Path] = []
        self._ref_index = 0
        self._backup = True
        self._range_start: int | None = None  # action range (indices into _paths)
        self._range_end: int | None = None
        self._selection: set[int] = set()  # multi-selected frame indices
        self._anchor: int | None = None

        # Folder picker.
        self._path_lbl = QLabel(tr("player.no_folder_loaded"))
        self._path_lbl.setStyleSheet("color:#888;")
        self._path_lbl.setMinimumWidth(0)
        self._path_lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        folder_btn = QPushButton(tr("player.choose_folder_btn"))
        folder_btn.clicked.connect(self._choose_folder)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("player.folder_label")))
        folder_row.addWidget(self._path_lbl, stretch=1)
        folder_row.addWidget(folder_btn)

        # Big image + prev/next.
        self._canvas = CropCanvas()
        self._canvas.box_changed.connect(self._update_hint)
        self._canvas.context_requested.connect(lambda: self._slide_menu_at(self._ref_index))
        self._ref_label = QLabel()
        prev_btn = QPushButton(tr("sort.prev"))
        prev_btn.clicked.connect(lambda: self._step_ref(-1))
        next_btn = QPushButton(tr("sort.next"))
        next_btn.clicked.connect(lambda: self._step_ref(1))
        ref_row = QHBoxLayout()
        ref_row.addWidget(prev_btn)
        ref_row.addWidget(self._ref_label, stretch=1)
        ref_row.addWidget(next_btn)

        # Film strip (browse only) with paging arrows.
        self._filmstrip = SortFilmstrip()
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.frame_clicked.connect(self._on_strip_click)
        self._filmstrip.frame_context.connect(self._slide_menu_at)
        strip_left = QPushButton("‹")
        strip_left.setFixedWidth(28)
        strip_left.setAutoRepeat(True)
        strip_left.setAutoRepeatInterval(60)
        strip_left.clicked.connect(lambda: self._filmstrip.scroll(-1))
        strip_right = QPushButton("›")
        strip_right.setFixedWidth(28)
        strip_right.setAutoRepeat(True)
        strip_right.setAutoRepeatInterval(60)
        strip_right.clicked.connect(lambda: self._filmstrip.scroll(1))
        strip_row = QHBoxLayout()
        strip_row.setSpacing(4)
        strip_row.addWidget(strip_left)
        strip_row.addWidget(self._filmstrip, stretch=1)
        strip_row.addWidget(strip_right)

        # Scroll bar to jump anywhere in the strip (for very long recordings).
        self._strip_scroll = QScrollBar(Qt.Horizontal)
        self._strip_scroll.valueChanged.connect(self._filmstrip.center_on)
        self._filmstrip.centered.connect(self._on_strip_centered)

        # Bottom row: hint/size (left) — mode toggle — Start (right).
        self._hint = QLabel()
        self._hint.setStyleSheet("color:#aaa;")
        self._mode_btn = QPushButton()
        self._mode_btn.clicked.connect(self._toggle_mode)
        self._start_btn = QPushButton(tr("common.start"))
        self._start_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self._start_btn.clicked.connect(self._start)
        bottom_row = QHBoxLayout()
        bottom_row.addWidget(self._hint, stretch=1)
        bottom_row.addWidget(self._mode_btn)
        bottom_row.addWidget(self._start_btn)

        self._status = QLabel()

        layout = QVBoxLayout(self)
        layout.addLayout(folder_row)
        layout.addLayout(ref_row)
        layout.addWidget(self._canvas, stretch=1)
        layout.addLayout(strip_row)
        layout.addWidget(self._strip_scroll)
        layout.addLayout(bottom_row)
        layout.addWidget(self._status)
        self.resize(960, 820)

        self._refresh_mode_btn()
        self._update_hint()
        if folder is not None:
            self._load_folder(folder)

    # ----- folder -----
    def _choose_folder(self) -> None:
        start = str(self._folder.parent if self._folder else get_data_dir())
        chosen = QFileDialog.getExistingDirectory(self, tr("sort.choose_folder"), start)
        if chosen:
            self._load_folder(Path(chosen))

    def _load_folder(self, folder: Path) -> None:
        folder = Path(folder)
        if not slide_frames(folder) and (folder / "folien").is_dir() and slide_frames(folder / "folien"):
            folder = folder / "folien"
        self._folder = folder
        set_last_session(webinar_dir(self._folder))  # share the folder with the other tools
        self._paths = slide_frames(self._folder)
        self._ref_index = 0
        self._path_lbl.setText(webinar_name(self._folder))
        self._path_lbl.setToolTip(str(self._folder))
        self._canvas.reset()
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._sync_scroll()
        self._status.setText(tr("sort.no_slides") if not self._paths else "")

    # ----- context menu (single / bulk / range) -----
    def _slide_menu_at(self, index: int) -> None:
        if not (0 <= index < len(self._paths)):
            return
        if len(self._selection) > 1 and index in self._selection:
            self._bulk_menu()
            return
        menu = QMenu(self)
        act_move = menu.addAction(tr("sort.menu_move"))
        act_del = menu.addAction(tr("sort.menu_delete"))
        menu.addSeparator()
        act_from = menu.addAction(tr("range.from_here"))
        act_to = menu.addAction(tr("range.to_here"))
        act_clear = menu.addAction(tr("range.clear"))
        act_clear.setEnabled(self._range_start is not None or self._range_end is not None)
        menu.addSeparator()
        t = slide_second(self._paths[index].name)
        act_discard = menu.addAction(tr("discard.from_here", time=fmt_seconds(t or 0)))
        act_discard.setEnabled(t is not None)
        chosen = menu.exec(QCursor.pos())
        if chosen == act_move:
            self._remove_slide_at(index, move=True)
        elif chosen == act_del:
            self._remove_slide_at(index, move=False)
        elif chosen == act_from:
            self._range_start = index
            self._apply_range_highlight()
        elif chosen == act_to:
            self._range_end = index
            self._apply_range_highlight()
        elif chosen == act_clear:
            self._clear_range()
        elif chosen == act_discard:
            self._discard_from(index)

    def _discard_from(self, index: int) -> None:
        """Discard the tail: trim the system track to this slide's second and delete
        all slides and mic segments at or after it (irreversible; confirmed)."""
        if not (0 <= index < len(self._paths)):
            return
        t = slide_second(self._paths[index].name)
        if t is None:
            return
        session = webinar_dir(self._folder)
        n_slides, n_mics = count_from_second(self._folder, session / "mikro", t)
        if not ask_yes_no(self, tr("discard.confirm_title"),
                          tr("discard.confirm_body", time=fmt_seconds(t), slides=n_slides, mics=n_mics)):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            discard_from_second(session, self._folder, t)
        finally:
            QApplication.restoreOverrideCursor()
        self._canvas.reset()
        self._paths = slide_frames(self._folder)
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._sync_scroll()
        self._status.setText(tr("discard.done", time=fmt_seconds(t), slides=n_slides, mics=n_mics))

    def _bulk_menu(self) -> None:
        n = len(self._selection)
        menu = QMenu(self)
        act_move = menu.addAction(tr("multi.move", n=n))
        act_del = menu.addAction(tr("multi.delete", n=n))
        chosen = menu.exec(QCursor.pos())
        if chosen == act_move:
            self._remove_selected(move=True)
        elif chosen == act_del:
            self._remove_selected(move=False)

    def _reload_showing(self, name: str) -> None:
        self._paths = slide_frames(self._folder)
        idx = next((i for i, p in enumerate(self._paths) if p.name == name), None)
        self._ref_index = idx if idx is not None else min(self._ref_index, max(0, len(self._paths) - 1))
        self._canvas.reset()
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._sync_scroll()

    def _remove_slide_at(self, index: int, move: bool) -> None:
        name = self._paths[index].name
        shown = self._paths[self._ref_index].name
        if move:
            if not move_slide(self._folder, name):
                return
        else:
            if not delete_slide(self, self._folder, name):
                return
        self._reload_showing(shown if shown != name else "")

    def _remove_selected(self, move: bool) -> None:
        names = [self._paths[i].name for i in sorted(self._selection) if 0 <= i < len(self._paths)]
        if not names:
            return
        if not move:
            if not ask_yes_no(self, tr("multi.delete_title"), tr("multi.delete_body", n=len(names))):
                return
        shown = self._paths[self._ref_index].name if 0 <= self._ref_index < len(self._paths) else None
        for name in names:
            if move:
                move_slide(self._folder, name)
            else:
                try:
                    (self._folder / name).unlink()
                except OSError:
                    pass
        self._reload_showing(shown if shown not in names else "")

    # ----- action range -----
    def _effective_range(self) -> tuple[int, int]:
        lo = self._range_start if self._range_start is not None else 0
        hi = self._range_end if self._range_end is not None else len(self._paths) - 1
        return (min(lo, hi), max(lo, hi))

    def _apply_range_highlight(self) -> None:
        if self._range_start is None and self._range_end is None:
            self._filmstrip.set_range(None)
        else:
            self._filmstrip.set_range(self._effective_range())

    def _clear_range(self) -> None:
        self._range_start = None
        self._range_end = None
        self._filmstrip.set_range(None)

    def _effective_range(self) -> tuple[int, int]:
        lo = self._range_start if self._range_start is not None else 0
        hi = self._range_end if self._range_end is not None else len(self._paths) - 1
        return (min(lo, hi), max(lo, hi))

    def _apply_range_highlight(self) -> None:
        if self._range_start is None and self._range_end is None:
            self._filmstrip.set_range(None)
        else:
            self._filmstrip.set_range(self._effective_range())

    def _clear_range(self) -> None:
        self._range_start = None
        self._range_end = None
        self._filmstrip.set_range(None)

    def _update_selection(self, index: int, modifiers) -> None:
        ctrl = bool(modifiers) and bool(modifiers & Qt.ControlModifier)
        shift = bool(modifiers) and bool(modifiers & Qt.ShiftModifier)
        if not ctrl and not shift:
            self._selection = set()
            self._anchor = index
        else:
            self._selection, self._anchor = next_selection(
                list(range(len(self._paths))), self._selection, self._anchor, index, ctrl, shift)
        self._filmstrip.set_selection(self._selection)

    def _clear_selection(self) -> None:
        self._selection = set()
        self._anchor = None
        self._filmstrip.set_selection(set())

    # ----- browsing -----
    def _on_strip_click(self, frame_index: int, modifiers=None) -> None:
        if 0 <= frame_index < len(self._paths):
            self._ref_index = frame_index
            self._refresh_ref()
            self._update_selection(frame_index, modifiers)
            self._filmstrip.center_on(self._ref_index)

    def _on_strip_centered(self, value: int) -> None:
        self._strip_scroll.blockSignals(True)
        self._strip_scroll.setValue(value)
        self._strip_scroll.blockSignals(False)

    def _sync_scroll(self) -> None:
        self._strip_scroll.blockSignals(True)
        self._strip_scroll.setRange(0, max(0, len(self._paths) - 1))
        self._strip_scroll.setValue(min(self._ref_index, max(0, len(self._paths) - 1)))
        self._strip_scroll.blockSignals(False)

    def _step_ref(self, delta: int) -> None:
        if not self._paths:
            return
        self._ref_index = (self._ref_index + delta) % len(self._paths)
        self._refresh_ref()
        self._filmstrip.center_on(self._ref_index)

    def _refresh_ref(self) -> None:
        if not self._paths:
            self._ref_label.setText("—")
            return
        path = self._paths[self._ref_index]
        self._canvas.set_image(frame_to_qpixmap(load_frame(path)))
        self._ref_label.setText(
            tr("sort.reference", i=self._ref_index + 1, n=len(self._paths), name=path.name)
        )

    # ----- bottom row -----
    def _update_hint(self) -> None:
        box = self._canvas.keep_box()
        if box is None:
            self._hint.setText(tr("crop.hint"))
            self._start_btn.setEnabled(False)
        else:
            l, t, r, b = box
            self._hint.setText(tr("crop.size", w=r - l, h=b - t))
            self._start_btn.setEnabled(True)

    def _toggle_mode(self) -> None:
        self._backup = not self._backup
        self._refresh_mode_btn()

    def _refresh_mode_btn(self) -> None:
        if self._backup:
            self._mode_btn.setText(tr("crop.mode_backup"))
            self._mode_btn.setStyleSheet("")
        else:
            self._mode_btn.setText(tr("crop.mode_overwrite").upper())  # red -> shout
            self._mode_btn.setStyleSheet("color: white; background: #b00;")

    def _start(self) -> None:
        box = self._canvas.keep_box()
        if box is None or not self._paths:
            return
        lo, hi = self._effective_range()
        # Warn if the crop was drawn on a slide that won't even be cropped.
        if not (lo <= self._ref_index <= hi):
            if not ask_yes_no(self, tr("range.outside_title"), tr("range.outside_body")):
                return
        # Restrict to the selected range (None = all slides).
        bounded = self._range_start is not None or self._range_end is not None
        names = {p.name for p in self._paths[lo:hi + 1]} if bounded else None
        if not self._backup:
            if not ask_yes_no(self, tr("crop.overwrite_title"), tr("crop.overwrite_body")):
                return
        total = len(names) if names is not None else len(self._paths)
        prog = QProgressDialog(tr("crop.working"), None, 0, total, self)
        prog.setWindowTitle(tr("progress.wait_title"))
        prog.setWindowModality(Qt.WindowModal)
        prog.setCancelButton(None)
        prog.setMinimumDuration(0)

        def on_progress(done: int, total: int) -> None:
            prog.setMaximum(total)
            prog.setValue(done)
            QApplication.processEvents()

        n = crop_folder(self._folder, box, backup=self._backup, progress=on_progress, names=names)
        prog.close()
        # Crop applied — sizes changed, so drop the rectangle and reload.
        self._canvas.reset()
        self._paths = slide_frames(self._folder)
        self._ref_index = min(self._ref_index, max(0, len(self._paths) - 1))
        self._refresh_ref()
        self._filmstrip.set_session(self._paths)
        self._filmstrip.set_browse_mode(True)
        self._filmstrip.center_on(self._ref_index)
        self._clear_range()
        self._clear_selection()
        self._sync_scroll()
        self._status.setText(tr("crop.done", n=n))


def open_cropper(folder: Path | None = None) -> CropWindow:
    win = CropWindow(folder or get_last_session())
    win.setWindowIcon(app_icon())
    win.show()
    return win


def main() -> int:
    from core.i18n import init_language

    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    init_language()
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    open_cropper(folder)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
