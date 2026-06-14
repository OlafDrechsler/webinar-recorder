"""Fullscreen translucent overlay for dragging a capture rectangle.

Used both at startup and whenever the user clicks "Bereich neu wählen" during
recording. Audio is unaffected; only the screenshot region changes.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from io_adapters.screen import Region, physical_region


class RegionSelector(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)
        self.setWindowOpacity(0.35)
        self._origin: QPoint | None = None
        self._rect = QRect()
        self.selected: Region | None = None
        # Cover the full virtual desktop (all monitors).
        geo = QGuiApplication.primaryScreen().virtualGeometry()
        self.setGeometry(geo)
        self._virtual_origin = geo.topLeft()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 120))
        if not self._rect.isNull():
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(self._rect, QColor(0, 0, 0, 0))
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 180, 255), 2)
            painter.setPen(pen)
            painter.drawRect(self._rect)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._origin = event.position().toPoint()
        self._rect = QRect(self._origin, self._origin)
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._origin is not None:
            self._rect = QRect(self._origin, event.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._rect.width() > 5 and self._rect.height() > 5:
            # Translate widget-local coords to absolute (logical) screen coords,
            # then scale to physical pixels so mss grabs exactly what was framed
            # even on a DPI-scaled display.
            ox, oy = self._virtual_origin.x(), self._virtual_origin.y()
            dpr = self.devicePixelRatioF()
            self.selected = physical_region(
                self._rect.left() + ox,
                self._rect.top() + oy,
                self._rect.width(),
                self._rect.height(),
                dpr,
            )
        self.close()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.selected = None
            self.close()


def select_region() -> Region | None:
    """Show the overlay modally and return the chosen Region (or None)."""
    selector = RegionSelector()
    selector.show()
    selector.activateWindow()
    selector.raise_()
    while selector.isVisible():
        QGuiApplication.processEvents()
    return selector.selected
