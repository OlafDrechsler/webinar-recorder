from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor

from gui.work_area import Stroke, stroke_hit, text_box_top


def test_text_box_top_centers_on_cursor():
    assert text_box_top(100, 40) == 80


def test_stroke_hit_near_segment():
    s = Stroke(pen=False, color=QColor(0, 0, 0), width=10, points=[QPointF(0, 0), QPointF(100, 0)])
    assert stroke_hit(s, QPointF(50, 3), 10) is True
    assert stroke_hit(s, QPointF(50, 50), 10) is False


def test_stroke_hit_single_point():
    s = Stroke(pen=True, color=QColor(0, 0, 0), width=8, points=[QPointF(10, 10)])
    assert stroke_hit(s, QPointF(12, 12), 8) is True
    assert stroke_hit(s, QPointF(40, 40), 8) is False


def test_stroke_hit_empty():
    s = Stroke(pen=True, color=QColor(0, 0, 0), width=8, points=[])
    assert stroke_hit(s, QPointF(0, 0), 8) is False
