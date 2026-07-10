"""Tests for gui.slide_ops (shared slide file operations)."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QValidator  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import gui.slide_ops as slide_ops  # noqa: E402
from core.i18n import tr  # noqa: E402
from gui.slide_ops import (  # noqa: E402
    _GuardedSpinBox,
    adjust_slide_time,
    delete_slide,
    fmt_seconds,
    move_slide,
    rename_second,
    safe_time_range,
    slide_second,
)

_app = QApplication.instance() or QApplication([])


def _stub_dialog(monkeypatch, value):
    class _Dlg:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return QDialog.Accepted

        def value(self):
            return value

    monkeypatch.setattr(slide_ops, "TimeAdjustDialog", _Dlg)


# ----- slide_second -----
def test_slide_second_auto():
    assert slide_second("00050.png") == 50


def test_slide_second_edit():
    assert slide_second("00318_edit_02.png") == 318


def test_slide_second_non_digit():
    assert slide_second("cover.png") is None


# ----- rename_second -----
def test_rename_second_keeps_suffix():
    assert rename_second("00050.png", 80) == "00080.png"
    assert rename_second("00050_edit_01.png", 7) == "00007_edit_01.png"


# ----- fmt_seconds -----
def test_fmt_seconds():
    assert fmt_seconds(0) == "00:00"
    assert fmt_seconds(75) == "01:15"
    assert fmt_seconds(-3) == "00:00"


# ----- safe_time_range -----
def test_range_between_neighbours():
    # seconds present: 10, 20, 40 ; current 20 -> gap (11..39)
    assert safe_time_range({10, 20, 40}, 20, None) == (11, 39)


def test_range_first_slide_starts_at_zero():
    assert safe_time_range({10, 20}, 10, None) == (0, 19)


def test_range_last_slide_uses_duration():
    # current 20 is the last slide; prev is 10 -> down to 11, up to the duration
    assert safe_time_range({10, 20}, 20, 300) == (11, 300)


def test_range_last_slide_without_duration_has_headroom():
    lo, hi = safe_time_range({10, 20}, 20, None)
    assert lo == 11 and hi == 20 + 600


def test_range_no_room_when_neighbours_adjacent():
    # 19 | 20 | 21 -> only value is 20 (lo == hi)
    assert safe_time_range({19, 20, 21}, 20, None) == (20, 20)


# ----- move_slide -----
def test_move_slide(tmp_path):
    (tmp_path / "00010.png").write_bytes(b"x")
    assert move_slide(tmp_path, "00010.png") is True
    assert (tmp_path / "_aussortiert" / "00010.png").exists()
    assert not (tmp_path / "00010.png").exists()


def test_move_slide_missing_returns_false(tmp_path):
    assert move_slide(tmp_path, "gone.png") is False


# ----- delete_slide -----
def test_delete_slide_confirmed(tmp_path, monkeypatch):
    (tmp_path / "00010.png").write_bytes(b"x")
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a, **k: True)
    assert delete_slide(None, tmp_path, "00010.png") is True
    assert not (tmp_path / "00010.png").exists()


def test_delete_slide_declined_keeps_file(tmp_path, monkeypatch):
    (tmp_path / "00010.png").write_bytes(b"x")
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a, **k: False)
    assert delete_slide(None, tmp_path, "00010.png") is False
    assert (tmp_path / "00010.png").exists()


# ----- guarded spin box -----
def test_guarded_spinbox_bounds_but_allows_typing_beyond():
    sb = _GuardedSpinBox(10, 20, 100, 15)
    assert (sb.minimum(), sb.maximum()) == (10, 20)              # arrows bounded
    assert sb.validate("50", 2)[0] == QValidator.Acceptable      # typing beyond hi ok
    assert sb.validate("200", 3)[0] == QValidator.Invalid        # beyond hard_max no
    sb._on_edited("50")
    assert sb.chosen_value() == 50                               # override kept
    sb._on_edited("15")
    assert sb.chosen_value() == 15                               # back inside -> value


# ----- adjust_slide_time -----
def _three(tmp_path):
    for n in ("00010.png", "00020.png", "00050.png"):
        (tmp_path / n).write_bytes(b"X" + n.encode())
    return {10, 20, 50}


def test_adjust_in_range_is_silent(tmp_path, monkeypatch):
    occ = _three(tmp_path)
    _stub_dialog(monkeypatch, 15)  # inside gap [11, 49] of cur=20
    seen = []
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a: seen.append(a[2]) or True)
    assert adjust_slide_time(None, tmp_path, "00020.png", occ) == "00015.png"
    assert (tmp_path / "00015.png").exists() and not (tmp_path / "00020.png").exists()
    assert seen == []  # no confirmation for an in-range move


def test_adjust_reorder_free_asks_plain(tmp_path, monkeypatch):
    occ = _three(tmp_path)
    _stub_dialog(monkeypatch, 5)  # below the gap -> reorder, second 5 is free
    seen = []
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a: seen.append(a[2]) or True)
    assert adjust_slide_time(None, tmp_path, "00020.png", occ) == "00005.png"
    assert seen == [tr("time.reorder_body")]


def test_adjust_reorder_onto_occupied_warns_and_overwrites(tmp_path, monkeypatch):
    occ = _three(tmp_path)
    _stub_dialog(monkeypatch, 10)  # second 10 already taken by 00010.png
    seen = []
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a: seen.append(a[2]) or True)
    assert adjust_slide_time(None, tmp_path, "00020.png", occ) == "00010.png"
    assert seen == [tr("time.reorder_occupied_body")]
    assert (tmp_path / "00010.png").read_bytes() == b"X00020.png"  # took its place
    assert not (tmp_path / "00020.png").exists()


def test_adjust_declined_changes_nothing(tmp_path, monkeypatch):
    occ = _three(tmp_path)
    _stub_dialog(monkeypatch, 5)
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a: False)
    assert adjust_slide_time(None, tmp_path, "00020.png", occ) is None
    assert (tmp_path / "00020.png").exists() and not (tmp_path / "00005.png").exists()
