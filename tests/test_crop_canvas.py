"""CropCanvas: after drawing the rectangle, its edges/corners can be grabbed to
resize and the inside grabbed to move (hit-testing + cursor feedback)."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.crop_out import CropCanvas  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _Move:
    """Minimal event exposing position().x()/y() at a fixed widget point."""

    def __init__(self, x, y):
        self._x, self._y = x, y

    def position(self):
        ev = self

        class _P:
            def x(self):
                return ev._x

            def y(self):
                return ev._y

        return _P()


def _canvas():
    c = CropCanvas()
    c.resize(800, 600)
    c.set_image(QPixmap(200, 100))
    c._box = [40.0, 20.0, 160.0, 80.0]
    return c


def _w(c, ix, iy):
    ox, oy, scale = c._disp()
    return ox + ix * scale, oy + iy * scale


def test_cursor_reflects_handle():
    c = _canvas()
    assert c._cursor_for(c._handle_at(*_w(c, 40, 50))) == Qt.SizeHorCursor    # left edge
    assert c._cursor_for(c._handle_at(*_w(c, 100, 80))) == Qt.SizeVerCursor   # bottom edge
    assert c._cursor_for(c._handle_at(*_w(c, 40, 20))) == Qt.SizeFDiagCursor  # TL corner
    assert c._cursor_for(c._handle_at(*_w(c, 100, 50))) == Qt.SizeAllCursor   # inside -> move
    assert c._cursor_for(c._handle_at(5, 5)) == Qt.ArrowCursor                # outside


def test_resize_right_edge():
    c = _canvas()
    c._mode = "resize"
    c._grab = (False, True, False, False)
    c.mouseMoveEvent(_Move(*_w(c, 120, 50)))
    assert round(c._box[2]) == 120 and c._box[0] == 40  # only right edge moved


def test_move_box_clamped():
    c = _canvas()
    c._mode = "move"
    c._box0 = [40.0, 20.0, 120.0, 80.0]
    c._move_from = (100, 50)
    c.mouseMoveEvent(_Move(*_w(c, 120, 60)))  # delta +20,+10
    assert c._box[0] == 60 and c._box[1] == 30 and c._box[2] == 140 and c._box[3] == 90


def test_resize_edges_do_not_cross():
    c = _canvas()
    c._mode = "resize"
    c._grab = (True, False, False, False)      # drag left edge far past the right
    c.mouseMoveEvent(_Move(*_w(c, 500, 50)))
    assert c._box[0] < c._box[2]               # stays a valid rectangle
