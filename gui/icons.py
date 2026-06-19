"""Crisp, antialiased transport icons drawn with QPainter (no font glyphs).

play / pause, double-triangle rewind+forward (for the transport buttons), and
round circular arrows with a "10" label (for the overlay). All vector, so they
stay smooth at any size.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

WHITE = QColor(255, 255, 255)


def _canvas(size: int):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.TextAntialiasing, True)
    return pm, p


def _triangle(p: QPainter, cx: float, cy: float, r: float, color: QColor, right: bool = True) -> None:
    path = QPainterPath()
    if right:
        path.moveTo(cx - r, cy - r)
        path.lineTo(cx + r, cy)
        path.lineTo(cx - r, cy + r)
    else:
        path.moveTo(cx + r, cy - r)
        path.lineTo(cx - r, cy)
        path.lineTo(cx + r, cy + r)
    path.closeSubpath()
    p.fillPath(path, color)


def play_pixmap(size: int, color: QColor = WHITE) -> QPixmap:
    pm, p = _canvas(size)
    _triangle(p, size * 0.46, size / 2, size * 0.27, color, right=True)
    p.end()
    return pm


def pause_pixmap(size: int, color: QColor = WHITE) -> QPixmap:
    pm, p = _canvas(size)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    bw = size * 0.15
    gap = size * 0.10        # small gap -> bars close together
    h = size * 0.56
    y = (size - h) / 2
    cx = size / 2
    r = bw * 0.45
    p.drawRoundedRect(QRectF(cx - gap / 2 - bw, y, bw, h), r, r)
    p.drawRoundedRect(QRectF(cx + gap / 2, y, bw, h), r, r)
    p.end()
    return pm


def rewind_pixmap(size: int, color: QColor = WHITE) -> QPixmap:
    pm, p = _canvas(size)
    r = size * 0.22
    cy = size / 2
    _triangle(p, size * 0.42, cy, r, color, right=False)
    _triangle(p, size * 0.66, cy, r, color, right=False)
    p.end()
    return pm


def forward_pixmap(size: int, color: QColor = WHITE) -> QPixmap:
    pm, p = _canvas(size)
    r = size * 0.22
    cy = size / 2
    _triangle(p, size * 0.34, cy, r, color, right=True)
    _triangle(p, size * 0.58, cy, r, color, right=True)
    p.end()
    return pm


def _circular_arrow(size: int, color: QColor, forward: bool, label: str) -> QPixmap:
    pm, p = _canvas(size)
    c = size / 2.0
    R = size * 0.32
    pen = QPen(color, max(2.0, size * 0.09))
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    rect = QRectF(c - R, c - R, 2 * R, 2 * R)

    # ~300° arc with the gap near the top. Qt angles: 0°=3 o'clock, CCW positive.
    if forward:                 # clockwise arrow, head upper-right
        start, span = 0.0, -300.0
    else:                       # counter-clockwise arrow, head upper-left
        start, span = 180.0, 300.0
    p.drawArc(rect, int(start * 16), int(span * 16))

    # Arrowhead at the arc's end, built from the tangent vector (screen coords).
    end = math.radians(start + span)
    px = c + R * math.cos(end)
    py = c - R * math.sin(end)
    if forward:                 # clockwise tangent
        tx, ty = math.sin(end), math.cos(end)
    else:                       # counter-clockwise tangent
        tx, ty = -math.sin(end), -math.cos(end)
    nx, ny = -ty, tx            # perpendicular
    hlen = size * 0.17
    hw = size * 0.12
    head = QPainterPath()
    head.moveTo(px + tx * hlen, py + ty * hlen)         # tip (along motion)
    head.lineTo(px + nx * hw, py + ny * hw)             # base corner
    head.lineTo(px - nx * hw, py - ny * hw)             # base corner
    head.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.fillPath(head, color)

    if label:
        f = QFont()
        f.setBold(True)
        f.setPixelSize(int(size * 0.30))
        p.setFont(f)
        p.setPen(color)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, label)
    p.end()
    return pm


# ----- QIcon wrappers -----
def play_icon(size: int = 22) -> QIcon:
    return QIcon(play_pixmap(size))


def pause_icon(size: int = 22) -> QIcon:
    return QIcon(pause_pixmap(size))


def rewind_icon(size: int = 22) -> QIcon:
    return QIcon(rewind_pixmap(size))


def forward_icon(size: int = 22) -> QIcon:
    return QIcon(forward_pixmap(size))


def skip_back_icon(size: int = 36, label: str = "10") -> QIcon:
    return QIcon(_circular_arrow(size, WHITE, forward=False, label=label))


def skip_forward_icon(size: int = 36, label: str = "10") -> QIcon:
    return QIcon(_circular_arrow(size, WHITE, forward=True, label=label))
