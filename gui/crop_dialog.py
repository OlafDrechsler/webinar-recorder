"""Crop dialog: drag the area to KEEP on a reference slide; everything outside is
trimmed off. The rectangle is returned in the reference image's pixel coordinates
so the sort-out tool can apply it to every slide (losslessly, see core.crop)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.crop import Box
from core.i18n import tr
from gui.dialogs import ask_yes_no


class CropCanvas(QWidget):
    """Shows a slide scaled to fit and lets the user drag one keep-rectangle. The
    area outside it is dimmed as a live preview."""

    box_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._pix: QPixmap | None = None
        self._box: list[int] | None = None  # [l, t, r, b] in image pixels
        self._drag_from: tuple[float, float] | None = None
        self.setMinimumSize(480, 320)

    def set_image(self, pix: QPixmap) -> None:
        self._pix = pix
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
        # A click without a drag (zero-size) means "no crop".
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
        # Dim everything outside the keep rectangle (the part being cropped away).
        shade = QColor(0, 0, 0, 140)
        p.fillRect(QRect(target.left(), target.top(), target.width(), keep.top() - target.top()), shade)
        p.fillRect(QRect(target.left(), keep.bottom(), target.width(), target.bottom() - keep.bottom()), shade)
        p.fillRect(QRect(target.left(), keep.top(), keep.left() - target.left(), keep.height()), shade)
        p.fillRect(QRect(keep.right(), keep.top(), target.right() - keep.right(), keep.height()), shade)
        p.setPen(QPen(QColor(45, 166, 255), 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(keep)


class CropDialog(QDialog):
    """Pick the keep-rectangle and how to save (backup originals vs overwrite)."""

    def __init__(self, parent, pix: QPixmap, icon=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("crop.title"))
        if icon is not None:
            self.setWindowIcon(icon)
        self._backup = True

        self._canvas = CropCanvas()
        self._canvas.set_image(pix)
        self._canvas.box_changed.connect(self._update_info)

        self._info = QLabel()
        self._info.setStyleSheet("color:#aaa;")
        hint = QLabel(tr("crop.hint"))
        hint.setStyleSheet("color:#888;")
        hint.setWordWrap(True)

        btn_backup = QPushButton(tr("crop.apply_backup"))
        btn_backup.clicked.connect(lambda: self._accept(backup=True))
        btn_over = QPushButton(tr("crop.apply_overwrite"))
        btn_over.clicked.connect(lambda: self._accept(backup=False))
        btn_cancel = QPushButton(tr("common.cancel"))
        btn_cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(hint, 1)
        buttons.addWidget(btn_backup)
        buttons.addWidget(btn_over)
        buttons.addWidget(btn_cancel)

        lay = QVBoxLayout(self)
        lay.addWidget(self._canvas, 1)
        lay.addWidget(self._info)
        lay.addLayout(buttons)
        self.resize(900, 660)
        self._update_info()

    def _update_info(self) -> None:
        box = self._canvas.keep_box()
        if box is None:
            self._info.setText(tr("crop.size_full"))
        else:
            l, t, r, b = box
            self._info.setText(tr("crop.size", w=r - l, h=b - t))

    def _accept(self, backup: bool) -> None:
        if self._canvas.keep_box() is None:
            QMessageBox.information(self, tr("crop.title"), tr("crop.none"))
            return
        if not backup:
            if not ask_yes_no(self, tr("crop.overwrite_title"), tr("crop.overwrite_body")):
                return
        self._backup = backup
        self.accept()

    def result_box(self) -> Box | None:
        return self._canvas.keep_box()

    def use_backup(self) -> bool:
        return self._backup
