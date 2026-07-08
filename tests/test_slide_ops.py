"""Tests for gui.slide_ops (shared slide file operations)."""

import gui.slide_ops as slide_ops
from gui.slide_ops import (
    delete_slide,
    fmt_seconds,
    move_slide,
    rename_second,
    safe_time_range,
    slide_second,
)


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
