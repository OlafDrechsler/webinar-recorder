"""Work area: a frozen snapshot the user annotates, saved as a flat PNG.

Object model: each annotation (highlighter stroke, pen stroke, text box) stays a
separate, editable object during the session and is only baked into the image on
"Speichern". That gives us:

* a highlighter that keeps a constant transparency no matter how often/slowly you
  pass over an area (each stroke is drawn once as a single path),
* an eraser that removes individual marks (only while unsaved — after saving they
  are part of the image),
* text boxes that can be moved, resized and re-edited, with automatic word wrap,
  so text can never run off the image unreachably.

Tools: Textmarker (semi-transparent), Stift (opaque), Text (movable box), and
Radierer. The Textmarker/Stift dropdowns carry a thickness slider with a live
preview; the Text dropdown a font-size slider; colours are listed below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from core.i18n import tr
from core.naming import marked_frame_name
from core.settings import get_work_area_geometry, set_work_area_geometry

HIGHLIGHTER = "highlighter"
PEN = "pen"
TEXT = "text"
ERASER = "eraser"

_HL_ALPHA = 95
_DEFAULT_HL_WIDTH = 18
_DEFAULT_PEN_WIDTH = 4
_DEFAULT_TEXT_SIZE = 28

# (translation key, colour)
PALETTE = [
    ("color.yellow", QColor(255, 235, 0)),
    ("color.red", QColor(230, 0, 0)),
    ("color.blue", QColor(0, 120, 255)),
    ("color.green", QColor(0, 170, 0)),
    ("color.black", QColor(0, 0, 0)),
    ("color.white", QColor(255, 255, 255)),
]


def frame_to_qimage(frame: np.ndarray) -> QImage:
    h, w, _ = frame.shape
    contiguous = np.ascontiguousarray(frame)
    return QImage(contiguous.data, w, h, 3 * w, QImage.Format_RGB888).copy()


def _swatch(color: QColor) -> QIcon:
    pm = QPixmap(24, 24)
    pm.fill(color)
    return QIcon(pm)


@dataclass
class Stroke:
    pen: bool                       # True = opaque pen, False = highlighter
    color: QColor
    width: float                    # image-space pixels
    points: list = field(default_factory=list)  # list[QPointF] in image coords


def _dist_point_segment(p: QPointF, a: QPointF, b: QPointF) -> float:
    ax, ay, bx, by, px, py = a.x(), a.y(), b.x(), b.y(), p.x(), p.y()
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def stroke_hit(stroke: Stroke, p: QPointF, tol: float) -> bool:
    """True if image-point ``p`` is within ``tol`` of the stroke (for the eraser)."""
    pts = stroke.points
    if not pts:
        return False
    if len(pts) == 1:
        return math.hypot(p.x() - pts[0].x(), p.y() - pts[0].y()) <= tol
    return any(_dist_point_segment(p, a, b) <= tol for a, b in zip(pts, pts[1:]))


def text_box_top(center_y: float, height: float) -> float:
    """Top so the box is vertically centred on the click point."""
    return center_y - height / 2.0


class _Grip(QWidget):
    """Bottom-right resize handle for a TextItem or ImageItem.

    With ``aspect`` set (width/height), the resize keeps that ratio — used for
    pasted images so a screenshot is never distorted.
    """

    def __init__(self, parent: QWidget, aspect: float | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.setCursor(Qt.SizeFDiagCursor)
        self._origin = QPoint()
        self._size = QSize()
        self._aspect = aspect

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setPen(QPen(QColor(150, 150, 150), 2))
        for d in (5, 10):
            p.drawLine(self.width() - d, self.height() - 2, self.width() - 2, self.height() - d)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._origin = event.globalPosition().toPoint()
        self._size = self.parent().size()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        delta = event.globalPosition().toPoint() - self._origin
        w = max(60, self._size.width() + delta.x())
        if self._aspect:
            h = max(28, round(w / self._aspect))
            w = round(h * self._aspect)  # keep the ratio exact
        else:
            h = max(28, self._size.height() + delta.y())
        self.parent().resize(w, h)


class TextItem(QWidget):
    """A movable/resizable, word-wrapping text box kept live until save."""

    STRIP = 15   # top drag strip height

    def __init__(self, canvas: "AnnotationCanvas", image_rect: QRectF, color: QColor, size_img: int) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self.image_rect = QRectF(image_rect)
        self.color = QColor(color)
        self.size_img = size_img
        self.edit = QTextEdit(self)
        self.edit.setAcceptRichText(False)
        self.edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.edit.setFrameStyle(0)
        self._grip = _Grip(self)
        self._drag_origin: QPoint | None = None
        self._restyle()

    def text(self) -> str:
        return self.edit.toPlainText()

    def _restyle(self) -> None:
        self.edit.setStyleSheet(
            "QTextEdit{background:rgba(255,255,255,28);border:none;"
            f"color:{self.color.name()};}}"
        )

    def apply_scale(self, scale: float) -> None:
        f = self.edit.font()
        f.setPixelSize(max(6, int(self.size_img * scale)))
        self.edit.setFont(f)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self.edit.setGeometry(2, self.STRIP, self.width() - 4, self.height() - self.STRIP - 2)
        self._grip.move(self.width() - 16, self.height() - 16)
        self._grip.raise_()
        if not self.canvas.laying_out:
            self.image_rect = self.canvas.widget_rect_to_image(self.geometry())

    def moveEvent(self, event) -> None:  # noqa: N802
        if not self.canvas.laying_out:
            self.image_rect = self.canvas.widget_rect_to_image(self.geometry())

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(QRect(0, 0, self.width(), self.STRIP), QColor(80, 80, 80, 140))
        p.setPen(QPen(QColor(150, 150, 150), 1, Qt.DashLine))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = event.globalPosition().toPoint()
        self._start_pos = self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self._start_pos + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = None


def fit_pasted_rect(pw: float, ph: float, bw: float, bh: float) -> QRectF:
    """Initial image-space rect for a pasted pixmap of size ``(pw, ph)`` placed on a
    base image of ``(bw, bh)``: shrink to fit fully (keeping the aspect ratio) when
    it is larger than the base, else keep its native size — centred either way."""
    if pw <= 0 or ph <= 0:
        return QRectF(0, 0, 0, 0)
    scale = min(bw / pw, bh / ph, 1.0)
    w, h = pw * scale, ph * scale
    return QRectF((bw - w) / 2.0, (bh - h) / 2.0, w, h)


class ImageItem(QWidget):
    """A movable/resizable pasted image (e.g. a screenshot), kept live until save.

    Always interactive (independent of the drawing tool): drag anywhere to move,
    the bottom-right grip resizes with a fixed aspect ratio, the ``×`` button top
    right removes it. Baked into the PNG by ``AnnotationCanvas.flattened``.
    """

    def __init__(self, canvas: "AnnotationCanvas", image_rect: QRectF, pixmap: QPixmap) -> None:
        super().__init__(canvas)
        self.canvas = canvas
        self.image_rect = QRectF(image_rect)
        self.pixmap = pixmap
        self._aspect = pixmap.width() / pixmap.height() if pixmap.height() else 1.0
        self._grip = _Grip(self, aspect=self._aspect)
        self._del = QPushButton("×", self)
        self._del.setFixedSize(16, 16)
        self._del.setCursor(Qt.PointingHandCursor)
        self._del.setStyleSheet(
            "QPushButton{background:rgba(60,60,60,180);color:white;border:none;font-weight:bold;}"
            "QPushButton:hover{background:rgba(200,40,40,220);}"
        )
        self._del.clicked.connect(self._remove)
        self._drag_origin: QPoint | None = None
        self.setCursor(Qt.SizeAllCursor)

    def _remove(self) -> None:
        if self in self.canvas._image_items:
            self.canvas._image_items.remove(self)
        self.deleteLater()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._grip.move(self.width() - 16, self.height() - 16)
        self._grip.raise_()
        self._del.move(self.width() - 16, 0)
        self._del.raise_()
        if not self.canvas.laying_out:
            self.image_rect = self.canvas.widget_rect_to_image(self.geometry())

    def moveEvent(self, event) -> None:  # noqa: N802
        if not self.canvas.laying_out:
            self.image_rect = self.canvas.widget_rect_to_image(self.geometry())

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(self.rect(), self.pixmap)
        p.setPen(QPen(QColor(150, 150, 150), 1, Qt.DashLine))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = event.globalPosition().toPoint()
        self._start_pos = self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self._start_pos + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = None


class AnnotationCanvas(QWidget):
    def __init__(self, base: QPixmap) -> None:
        super().__init__()
        self._base = base
        self.setMinimumSize(320, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tool = HIGHLIGHTER
        self.color = QColor(255, 235, 0)
        self.hl_width = _DEFAULT_HL_WIDTH
        self.pen_width = _DEFAULT_PEN_WIDTH
        self.text_size = _DEFAULT_TEXT_SIZE
        self._marks: list[Stroke] = []
        self._text_items: list[TextItem] = []
        self._image_items: list[ImageItem] = []
        self._active: Stroke | None = None
        self._erasing = False
        self.laying_out = False
        self.set_tool(HIGHLIGHTER)

    # ----- tool / colour / sizes -----
    def set_tool(self, tool: str) -> None:
        self.tool = tool
        self.setCursor(Qt.IBeamCursor if tool == TEXT else Qt.CrossCursor)
        # Text boxes are only interactive in TEXT mode; otherwise clicks pass
        # through so strokes can be drawn over them and the eraser can hit them.
        passthrough = tool != TEXT
        for item in self._text_items:
            item.setAttribute(Qt.WA_TransparentForMouseEvents, passthrough)

    def set_color(self, color: QColor) -> None:
        self.color = QColor(color)

    def set_width(self, tool: str, value: int) -> None:
        if tool == HIGHLIGHTER:
            self.hl_width = value
        else:
            self.pen_width = value

    def set_text_size(self, value: int) -> None:
        self.text_size = value

    # ----- coordinate mapping -----
    def _display_rect(self) -> QRect:
        scale = self._scale()
        dw, dh = int(self._base.width() * scale), int(self._base.height() * scale)
        return QRect((self.width() - dw) // 2, (self.height() - dh) // 2, dw, dh)

    def _scale(self) -> float:
        # Never enlarge beyond native resolution — upscaling a screenshot looks
        # pixelated/soft. Shrink to fit when the window is smaller, else show 1:1.
        return min(self.width() / self._base.width(), self.height() / self._base.height(), 1.0)

    def _to_image(self, p: QPoint) -> QPointF:
        rect, scale = self._display_rect(), self._scale()
        ix = (p.x() - rect.left()) / scale
        iy = (p.y() - rect.top()) / scale
        ix = max(0, min(self._base.width() - 1, ix))
        iy = max(0, min(self._base.height() - 1, iy))
        return QPointF(ix, iy)

    def _to_widget_rect(self, ir: QRectF) -> QRect:
        rect, scale = self._display_rect(), self._scale()
        return QRect(
            int(rect.left() + ir.left() * scale), int(rect.top() + ir.top() * scale),
            int(ir.width() * scale), int(ir.height() * scale),
        )

    def widget_rect_to_image(self, qr: QRect) -> QRectF:
        rect, scale = self._display_rect(), self._scale()
        return QRectF(
            (qr.left() - rect.left()) / scale, (qr.top() - rect.top()) / scale,
            qr.width() / scale, qr.height() / scale,
        )

    # ----- text boxes -----
    def _create_text(self, image_pt: QPointF) -> None:
        w = min(self._base.width() * 0.5, 260.0)
        h = self.text_size * 2.4
        rect = QRectF(image_pt.x(), text_box_top(image_pt.y(), h), w, h)
        item = TextItem(self, rect, self.color, self.text_size)
        self._text_items.append(item)
        self.laying_out = True
        item.setGeometry(self._to_widget_rect(rect))
        item.apply_scale(self._scale())
        self.laying_out = False
        item.show()
        item.edit.setFocus()

    def _relayout_text_items(self) -> None:
        scale = self._scale()
        self.laying_out = True
        for item in self._text_items:
            item.setGeometry(self._to_widget_rect(item.image_rect))
            item.apply_scale(scale)
        for item in self._image_items:
            item.setGeometry(self._to_widget_rect(item.image_rect))
        self.laying_out = False

    # ----- pasted images -----
    def paste_from_clipboard(self) -> bool:
        """Paste an image from the clipboard as a movable/resizable object.

        Returns False when the clipboard holds no image (so the window can show a
        hint instead)."""
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            return False
        pm = QPixmap.fromImage(img)
        rect = fit_pasted_rect(pm.width(), pm.height(), self._base.width(), self._base.height())
        item = ImageItem(self, rect, pm)
        self._image_items.append(item)
        self.laying_out = True
        item.setGeometry(self._to_widget_rect(rect))
        self.laying_out = False
        item.show()
        item.raise_()
        return True

    # ----- eraser -----
    def _erase_at(self, widget_pt: QPoint, image_pt: QPointF) -> None:
        self._marks = [s for s in self._marks if not stroke_hit(s, image_pt, s.width / 2 + 5)]
        for item in list(self._text_items):
            if item.geometry().contains(widget_pt):
                self._text_items.remove(item)
                item.deleteLater()
        self.update()

    # ----- painting -----
    def resizeEvent(self, event) -> None:  # noqa: N802
        self._relayout_text_items()

    def _draw_marks(self, painter: QPainter) -> None:
        for s in self._marks:
            if not s.points:
                continue
            col = QColor(s.color)
            if not s.pen:
                col.setAlpha(_HL_ALPHA)
            painter.setPen(QPen(col, s.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            painter.setBrush(Qt.NoBrush)
            if len(s.points) == 1:
                painter.drawPoint(s.points[0])
            else:
                path = QPainterPath(s.points[0])
                for pt in s.points[1:]:
                    path.lineTo(pt)
                painter.drawPath(path)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(30, 30, 30))
        rect = self._display_rect()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)  # no pixelation when scaled
        painter.drawPixmap(rect, self._base)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.translate(rect.topLeft())
        painter.scale(self._scale(), self._scale())
        painter.setClipRect(QRectF(0, 0, self._base.width(), self._base.height()))
        self._draw_marks(painter)
        painter.restore()

    # ----- mouse -----
    def mousePressEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        ip = self._to_image(pt)
        if self.tool == TEXT:
            self._create_text(ip)
        elif self.tool == ERASER:
            self._erasing = True
            self._erase_at(pt, ip)
        else:
            width = self.hl_width if self.tool == HIGHLIGHTER else self.pen_width
            self._active = Stroke(pen=self.tool == PEN, color=QColor(self.color),
                                  width=width, points=[ip])
            self._marks.append(self._active)
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        pt = event.position().toPoint()
        ip = self._to_image(pt)
        if self._active is not None:
            self._active.points.append(ip)
            self.update()
        elif self._erasing:
            self._erase_at(pt, ip)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._active = None
        self._erasing = False

    # ----- export -----
    def flattened(self) -> QImage:
        result = QPixmap(self._base.size())
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.drawPixmap(0, 0, self._base)
        self._draw_marks(painter)  # marks already in image coordinates
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for item in self._image_items:  # pasted images sit above the strokes
            painter.drawPixmap(item.image_rect, item.pixmap, QRectF(item.pixmap.rect()))
        for item in self._text_items:
            txt = item.text()
            if not txt.strip():
                continue
            f = QFont(item.edit.font())   # same real UI font family as the editor
            f.setPixelSize(item.size_img)
            painter.setFont(f)
            painter.setPen(item.color)
            painter.drawText(item.image_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, txt)
        painter.end()
        return result.toImage()


class WorkAreaWindow(QWidget):
    saved = Signal(str)  # emitted with the saved filename (for the player to refresh)

    def __init__(self, frame: np.ndarray, seconds: int, slides_dir: Path,
                 save_as: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(tr("edit.title", sec=seconds))
        self._seconds = seconds
        self._slides_dir = Path(slides_dir)
        self._save_as = save_as

        base = QPixmap.fromImage(frame_to_qimage(frame))
        self._canvas = AnnotationCanvas(base)
        self._status = QLabel("")

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._tool_button(tr("edit.highlighter"), HIGHLIGHTER))
        toolbar.addWidget(self._tool_button(tr("edit.pen"), PEN))
        toolbar.addWidget(self._tool_button(tr("edit.text"), TEXT))
        eraser_btn = QPushButton(tr("edit.eraser"))
        eraser_btn.clicked.connect(lambda: self._canvas.set_tool(ERASER))
        toolbar.addWidget(eraser_btn)
        paste_btn = QPushButton(tr("edit.paste"))
        paste_btn.clicked.connect(self._paste)
        toolbar.addWidget(paste_btn)
        save_btn = QPushButton(tr("common.save"))
        save_btn.clicked.connect(self._save)
        toolbar.addWidget(save_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._canvas, stretch=1)
        layout.addWidget(self._status)

        geom = get_work_area_geometry()
        if geom is not None:
            self.setGeometry(*geom)
        else:
            self.resize(min(base.width() + 40, 1200), min(base.height() + 110, 800))

    # ----- tool dropdowns -----
    def _tool_button(self, label: str, tool: str) -> QPushButton:
        btn = QPushButton(label)
        menu = QMenu(btn)
        if tool == TEXT:
            self._add_size_widget(menu)
        else:
            self._add_thickness_widget(menu, tool)
        menu.addSeparator()
        for cname, color in PALETTE:
            act = menu.addAction(_swatch(color), tr(cname))
            act.triggered.connect(lambda _=False, c=color: self._canvas.set_color(c))
        menu.aboutToShow.connect(lambda: self._canvas.set_tool(tool))
        btn.setMenu(menu)
        return btn

    def _add_thickness_widget(self, menu: QMenu, tool: str) -> None:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(8, 6, 8, 6)
        v.addWidget(QLabel(tr("edit.thickness")))
        slider = QSlider(Qt.Horizontal)
        if tool == HIGHLIGHTER:
            slider.setRange(4, 60)
            slider.setValue(self._canvas.hl_width)
        else:
            slider.setRange(1, 30)
            slider.setValue(self._canvas.pen_width)
        preview = _ThicknessPreview()
        preview.set(slider.value(), self._canvas.color, tool == HIGHLIGHTER)
        slider.valueChanged.connect(
            lambda val: (self._canvas.set_width(tool, val),
                         preview.set(val, self._canvas.color, tool == HIGHLIGHTER))
        )
        v.addWidget(slider)
        v.addWidget(preview)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(container)
        menu.addAction(wa)

    def _add_size_widget(self, menu: QMenu) -> None:
        container = QWidget()
        v = QVBoxLayout(container)
        v.setContentsMargins(8, 6, 8, 6)
        header = QLabel()
        slider = QSlider(Qt.Horizontal)
        slider.setRange(10, 96)
        slider.setValue(self._canvas.text_size)
        # Yellow "Lorem ipsum" sample at the chosen size (consistent with Gelb).
        sample = QLabel("Lorem ipsum")
        sample.setStyleSheet("color: rgb(255,235,0);")
        sample.setMaximumWidth(280)

        def on_size(val: int) -> None:
            self._canvas.set_text_size(val)
            header.setText(tr("edit.font_size", n=val))
            f = sample.font()
            f.setPixelSize(val)
            sample.setFont(f)

        slider.valueChanged.connect(on_size)
        on_size(slider.value())
        v.addWidget(header)
        v.addWidget(slider)
        v.addWidget(sample)
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(container)
        menu.addAction(wa)

    def _paste(self) -> None:
        if not self._canvas.paste_from_clipboard():
            self._status.setText(tr("edit.paste_empty"))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        # A focused text box handles Ctrl+V itself (Qt delivers to it first), so
        # this only fires when the canvas/window has focus — never steals paste
        # from text editing.
        if event.matches(QKeySequence.Paste):
            self._paste()
            return
        super().keyPressEvent(event)

    def _save(self) -> None:
        if self._save_as:
            name = self._save_as
        else:
            existing = [p.name for p in self._slides_dir.glob("*.png")]
            name = marked_frame_name(self._seconds, existing)
        self._canvas.flattened().save(str(self._slides_dir / name), "PNG")
        self.saved.emit(name)
        self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        g = self.geometry()
        set_work_area_geometry(g.x(), g.y(), g.width(), g.height())
        super().closeEvent(event)


class _ThicknessPreview(QWidget):
    """Shows the current stroke width as a short line plus the pixel value."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(42)
        self.setMinimumWidth(180)
        self._w = 8
        self._color = QColor(0, 0, 0)
        self._hl = False

    def set(self, width: int, color: QColor, highlighter: bool) -> None:
        self._w = width
        self._color = QColor(color)
        self._hl = highlighter
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        c = QColor(self._color)
        if self._hl:
            c.setAlpha(_HL_ALPHA)
        pen = QPen(c, min(self._w, self.height() - 10))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        y = self.height() / 2
        p.drawLine(12, int(y), self.width() - 48, int(y))
        p.setPen(QColor(150, 150, 150))
        p.drawText(self.rect().adjusted(0, 0, -6, 0), Qt.AlignRight | Qt.AlignVCenter, f"{self._w} px")
