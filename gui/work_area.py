"""Work area: a frozen snapshot the user annotates and saves.

Opened when "Textmarker" is clicked. It shows the slide as it looked at the
click moment; the live capture loop keeps running independently. The user marks
the snapshot and clicks save; the annotated image is written with the
click-time second and a running counter (00137_markiert_01.png, _02, ...).

The canvas scales to fit the (resizable) window while annotations are always
drawn onto a full-resolution overlay, so the saved image keeps full quality
regardless of the on-screen zoom. Mouse coordinates are mapped from widget
space back to image space for this.

Tools: Textmarker (semi-transparent highlight), Stift (freehand), Text (click
to place a caret and type directly into the image).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.naming import marked_frame_name
from core.settings import get_work_area_geometry, set_work_area_geometry

HIGHLIGHTER = "highlighter"
PEN = "pen"
TEXT = "text"

TEXT_PX = 24  # text size in image pixels

# Colour palette offered in each tool's dropdown. The user picks tool + colour in
# one click, so e.g. choosing "Text" + black can't accidentally inherit the
# highlighter's yellow.
PALETTE = [
    ("Gelb", QColor(255, 235, 0)),
    ("Rosa", QColor(255, 105, 180)),
    ("Blau", QColor(0, 120, 255)),
    ("Grün", QColor(0, 170, 0)),
    ("Schwarz", QColor(0, 0, 0)),
    ("Weiß", QColor(255, 255, 255)),
]


def _swatch_icon(color: QColor) -> QIcon:
    """A small filled square used as the colour swatch in the dropdown."""
    pm = QPixmap(24, 24)
    pm.fill(color)
    return QIcon(pm)


def frame_to_qimage(frame: np.ndarray) -> QImage:
    h, w, _ = frame.shape
    contiguous = np.ascontiguousarray(frame)
    img = QImage(contiguous.data, w, h, 3 * w, QImage.Format_RGB888)
    return img.copy()  # detach from the numpy buffer


class AnnotationCanvas(QWidget):
    def __init__(self, base: QPixmap) -> None:
        super().__init__()
        self._base = base
        self._overlay = QPixmap(base.size())
        self._overlay.fill(Qt.transparent)
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.tool = HIGHLIGHTER
        self.color = QColor(255, 235, 0)
        self._last_img: QPoint | None = None
        self._editor: QLineEdit | None = None

    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.setCursor(Qt.IBeamCursor if tool == TEXT else Qt.CrossCursor)

    def set_color(self, color: QColor) -> None:
        self.color = color

    # ----- coordinate mapping between widget space and full-res image space -----
    def _display_rect(self) -> QRect:
        bw, bh = self._base.width(), self._base.height()
        W, H = self.width(), self.height()
        scale = min(W / bw, H / bh)
        dw, dh = int(bw * scale), int(bh * scale)
        return QRect((W - dw) // 2, (H - dh) // 2, dw, dh)

    def _scale(self) -> float:
        return min(self.width() / self._base.width(), self.height() / self._base.height())

    def _to_image(self, p: QPoint) -> QPoint:
        rect = self._display_rect()
        scale = self._scale()
        ix = (p.x() - rect.left()) / scale
        iy = (p.y() - rect.top()) / scale
        ix = max(0, min(self._base.width() - 1, ix))
        iy = max(0, min(self._base.height() - 1, iy))
        return QPoint(int(ix), int(iy))

    def _pen_for_tool(self) -> QPen:
        if self.tool == HIGHLIGHTER:
            c = QColor(self.color)
            c.setAlpha(90)
            return QPen(c, 18, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        return QPen(self.color, 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    # ----- painting -----
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        rect = self._display_rect()
        painter.drawPixmap(rect, self._base)
        painter.drawPixmap(rect, self._overlay)

    # ----- mouse -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self.tool == TEXT:
            self._begin_text(event.position().toPoint())
            return
        self._last_img = self._to_image(event.position().toPoint())

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._last_img is None or self.tool == TEXT:
            return
        cur = self._to_image(event.position().toPoint())
        painter = QPainter(self._overlay)
        painter.setPen(self._pen_for_tool())
        painter.drawLine(self._last_img, cur)
        painter.end()
        self._last_img = cur
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._last_img = None

    # ----- inline text editing -----
    def _begin_text(self, widget_pos: QPoint) -> None:
        if self._editor is not None:
            self._commit_text()
        editor = QLineEdit(self)
        scale = self._scale()
        editor.setStyleSheet(
            f"background: rgba(255,255,255,180); color: {self.color.name()};"
            " border: 1px dashed #888;"
        )
        font = editor.font()
        font.setPixelSize(max(8, int(TEXT_PX * scale)))
        editor.setFont(font)
        editor.move(widget_pos)
        editor.resize(240, int(TEXT_PX * scale) + 10)
        editor.show()
        editor.setFocus()
        editor.returnPressed.connect(self._commit_text)
        editor.editingFinished.connect(self._commit_text)
        self._editor = editor

    def commit_pending_text(self) -> None:
        """Flush a still-open inline text editor onto the overlay (used on save)."""
        if self._editor is not None:
            self._commit_text()

    def _commit_text(self) -> None:
        editor = self._editor
        if editor is None:
            return
        self._editor = None  # guard against re-entry from editingFinished
        text = editor.text()
        if text:
            img_pos = self._to_image(editor.pos())
            painter = QPainter(self._overlay)
            painter.setPen(QPen(self.color))
            font = painter.font()
            font.setPixelSize(TEXT_PX)
            painter.setFont(font)
            painter.drawText(QPoint(img_pos.x(), img_pos.y() + TEXT_PX), text)
            painter.end()
            self.update()
        editor.deleteLater()

    # ----- export -----
    def flattened(self) -> QImage:
        result = QPixmap(self._base.size())
        painter = QPainter(result)
        painter.drawPixmap(0, 0, self._base)
        painter.drawPixmap(0, 0, self._overlay)
        painter.end()
        return result.toImage()


class WorkAreaWindow(QWidget):
    saved = Signal(str)  # emitted with the saved filename (for the player to refresh)

    def __init__(self, frame: np.ndarray, seconds: int, slides_dir: Path) -> None:
        super().__init__()
        self.setWindowTitle(f"Arbeitsbereich – Sekunde {seconds}")
        self._seconds = seconds
        self._slides_dir = Path(slides_dir)

        base = QPixmap.fromImage(frame_to_qimage(frame))
        self._canvas = AnnotationCanvas(base)
        self._status = QLabel("")

        # Each tool button opens a colour dropdown; picking a swatch activates the
        # tool with that colour in one click (no separate "Farbe" button).
        toolbar = QHBoxLayout()
        for label, tool in (("Textmarker", HIGHLIGHTER), ("Stift", PEN), ("Text", TEXT)):
            btn = QPushButton(label)
            menu = QMenu(btn)
            for cname, color in PALETTE:
                act = menu.addAction(_swatch_icon(color), cname)
                act.triggered.connect(
                    lambda _=False, t=tool, c=color, n=cname, lbl=label: self._choose(t, c, n, lbl)
                )
            btn.setMenu(menu)  # a click on the button shows the menu
            toolbar.addWidget(btn)
        save_btn = QPushButton("Speichern")
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._status)

        # Debounced writer so a drag/resize doesn't hammer the settings file.
        self._geom_timer = QTimer(self)
        self._geom_timer.setSingleShot(True)
        self._geom_timer.setInterval(400)
        self._geom_timer.timeout.connect(self._persist_geometry)

        # Restore the last position/size (so it stays clear of the capture area),
        # else open at a sensible default. Set after the timer exists because
        # setGeometry/resize trigger move/resize events.
        geom = get_work_area_geometry()
        if geom is not None:
            x, y, w, h = geom
            self.setGeometry(x, y, w, h)
        else:
            self.resize(min(base.width() + 40, 1200), min(base.height() + 90, 800))

    def _choose(self, tool: str, color: QColor, color_name: str, tool_label: str) -> None:
        self._canvas.set_color(color)
        self._canvas.set_tool(tool)
        self._status.setText(f"Werkzeug: {tool_label} ({color_name})")

    # ----- remember window position/size -----
    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if hasattr(self, "_geom_timer"):
            self._geom_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "_geom_timer"):
            self._geom_timer.start()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._persist_geometry()
        super().closeEvent(event)

    def _persist_geometry(self) -> None:
        g = self.geometry()
        set_work_area_geometry(g.x(), g.y(), g.width(), g.height())

    def _save(self) -> None:
        # Commit any open inline text, write one PNG, then close — saving the same
        # frozen frame twice would only produce duplicates at the same timestamp.
        self._canvas.commit_pending_text()
        existing = [p.name for p in self._slides_dir.glob("*.png")]
        name = marked_frame_name(self._seconds, existing)
        self._canvas.flattened().save(str(self._slides_dir / name), "PNG")
        self.saved.emit(name)
        self.close()
