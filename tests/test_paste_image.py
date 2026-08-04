"""Pasting a clipboard image as a movable/resizable object in the work-area editor."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QGuiApplication, QImage, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.work_area import AnnotationCanvas, ImageItem, fit_pasted_rect  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_fit_pasted_rect_larger_scales_to_fit():
    r = fit_pasted_rect(400, 200, 100, 100)  # 2:1 image into a 100x100 slide
    assert round(r.width()) == 100 and round(r.height()) == 50  # fully visible
    assert abs(r.width() / r.height() - 2.0) < 1e-6             # aspect preserved
    assert round(r.x()) == 0 and round(r.y()) == 25            # centred


def test_fit_pasted_rect_smaller_keeps_native_and_centres():
    r = fit_pasted_rect(40, 20, 100, 100)  # fits -> native size
    assert round(r.width()) == 40 and round(r.height()) == 20
    assert round(r.x()) == 30 and round(r.y()) == 40


def test_flattened_bakes_image_item():
    base = QPixmap(100, 100)
    base.fill(QColor(0, 0, 0))
    canvas = AnnotationCanvas(base)
    pm = QPixmap(20, 20)
    pm.fill(QColor(255, 0, 0))
    rect = fit_pasted_rect(20, 20, 100, 100)  # native, centred at (40,40)-(60,60)
    canvas._image_items.append(ImageItem(canvas, rect, pm))
    out = canvas.flattened()
    assert out.pixelColor(50, 50) == QColor(255, 0, 0)  # covered by the pasted image
    assert out.pixelColor(5, 5) == QColor(0, 0, 0)      # corner still the base


def test_paste_from_empty_clipboard_returns_false():
    QGuiApplication.clipboard().clear()
    base = QPixmap(100, 100)
    base.fill(QColor(0, 0, 0))
    canvas = AnnotationCanvas(base)
    assert canvas.paste_from_clipboard() is False
    assert canvas._image_items == []


def test_paste_from_clipboard_adds_item():
    img = QImage(30, 15, QImage.Format_RGB888)
    img.fill(QColor(0, 255, 0))
    QGuiApplication.clipboard().setImage(img)
    base = QPixmap(100, 100)
    base.fill(QColor(0, 0, 0))
    canvas = AnnotationCanvas(base)
    assert canvas.paste_from_clipboard() is True
    assert len(canvas._image_items) == 1
    item = canvas._image_items[0]
    assert item.pixmap.width() == 30 and item.pixmap.height() == 15


def test_image_item_remove():
    base = QPixmap(100, 100)
    base.fill(QColor(0, 0, 0))
    canvas = AnnotationCanvas(base)
    pm = QPixmap(10, 10)
    pm.fill(QColor(0, 0, 255))
    item = ImageItem(canvas, fit_pasted_rect(10, 10, 100, 100), pm)
    canvas._image_items.append(item)
    item._remove()
    assert canvas._image_items == []
