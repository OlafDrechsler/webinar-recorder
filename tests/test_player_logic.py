"""Pure-logic tests for player/play.py helpers (no QApplication needed)."""

from core.filmstrip import build_filmstrip
from gui.slide_ops import rename_second as _rename_second
from player.play import (
    _find_track,
    _fmt,
    _wait_file_writable,
    latest_index_at_or_before,
    merge_strip_items,
    strip_caption,
)


# ----- _fmt -----
def test_fmt():
    assert _fmt(0) == "00:00"
    assert _fmt(999) == "00:00"          # truncates, no rounding up
    assert _fmt(61_000) == "01:01"
    assert _fmt(3_599_000) == "59:59"
    assert _fmt(-5_000) == "00:00"       # clamped, never negative


# ----- _rename_second -----
def test_rename_second_auto():
    assert _rename_second("00050.png", 80) == "00080.png"


def test_rename_second_keeps_edit_suffix():
    assert _rename_second("00050_edit_01.png", 80) == "00080_edit_01.png"


def test_rename_second_keeps_legacy_markiert_suffix():
    assert _rename_second("00050_markiert_02.png", 7) == "00007_markiert_02.png"


def test_rename_second_non_digit_name_unchanged():
    assert _rename_second("cover.png", 30) == "cover.png"


def test_rename_second_grows_past_five_digits():
    assert _rename_second("00050.png", 123456) == "123456.png"


# ----- _find_track -----
def test_find_track_prefers_mp3_over_wav(tmp_path):
    (tmp_path / "system.wav").write_bytes(b"x")
    (tmp_path / "system.mp3").write_bytes(b"x")
    assert _find_track(tmp_path, "system").suffix == ".mp3"


def test_find_track_falls_back_to_wav(tmp_path):
    (tmp_path / "system.wav").write_bytes(b"x")
    assert _find_track(tmp_path, "system").suffix == ".wav"


def test_find_track_none_when_missing(tmp_path):
    assert _find_track(tmp_path, "system") is None


# ----- merge_strip_items -----
def _frames(*names):
    return build_filmstrip(list(names))


def test_merge_orders_by_second_slide_before_mic():
    frames = _frames("00010.png", "00020.png", "00020_edit_01.png", "00040.png")
    items = merge_strip_items(frames, [(15_000, 18_000), (20_000, 23_000)])
    kinds = [(it["kind"], it["second"], it.get("name")) for it in items]
    assert kinds == [
        ("slide", 10, "00010.png"),
        ("mic", 15, None),
        ("slide", 20, "00020.png"),
        ("slide", 20, "00020_edit_01.png"),  # same-second slides stay together
        ("mic", 20, None),                   # mic sorts after the slides of its second
        ("slide", 40, "00040.png"),
    ]


def test_merge_empty_inputs():
    assert merge_strip_items([], []) == []
    assert [it["kind"] for it in merge_strip_items([], [(5_000, 6_000)])] == ["mic"]


# ----- latest_index_at_or_before -----
def test_latest_index_walkthrough():
    frames = _frames("00010.png", "00020.png", "00040.png")
    items = merge_strip_items(frames, [(15_000, 18_000), (30_000, 33_000)])
    # order: slide10, mic15, slide20, mic30, slide40
    assert latest_index_at_or_before(items, 5) is None      # before everything
    assert latest_index_at_or_before(items, 10) == 0
    assert latest_index_at_or_before(items, 14) == 0
    assert latest_index_at_or_before(items, 15) == 1        # mic reached
    assert latest_index_at_or_before(items, 19) == 1        # stays past audio end
    assert latest_index_at_or_before(items, 20) == 2        # next element takes over
    assert latest_index_at_or_before(items, 30) == 3
    assert latest_index_at_or_before(items, 39) == 3
    assert latest_index_at_or_before(items, 40) == 4
    assert latest_index_at_or_before(items, 9999) == 4


def test_latest_index_empty():
    assert latest_index_at_or_before([], 10) is None


# ----- strip_caption -----
def test_caption_slide():
    item = {"kind": "slide", "name": "00318.png", "second": 318}
    assert strip_caption(item) == "00318.png - 05:18"


def test_caption_mic_with_known_length():
    item = {"kind": "mic", "second": 15, "start_ms": 15_000, "end_ms": 42_000}
    assert strip_caption(item) == "M - 00:15 - 00:42"


def test_caption_mic_length_not_loaded_yet():
    item = {"kind": "mic", "second": 15, "start_ms": 15_000, "end_ms": 15_000}
    assert strip_caption(item) == "M - 00:15"


# ----- _wait_file_writable -----
def test_wait_file_writable_immediate(tmp_path):
    p = tmp_path / "a.mp3"
    p.write_bytes(b"x")
    assert _wait_file_writable(p, tries=3) is True


def test_wait_file_writable_missing_times_out(tmp_path):
    assert _wait_file_writable(tmp_path / "gone.mp3", tries=2) is False
