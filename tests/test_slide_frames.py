"""gui.sort_out.slide_frames returns every slide scheme, player-ordered."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.sort_out import slide_frames  # noqa: E402

_app = QApplication.instance() or QApplication([])


def test_slide_frames_includes_all_schemes_ordered(tmp_path):
    for n in ("00020.png", "00010.png", "00020_01.png", "00030_edit_01.png",
              "00030_markiert_02.png", "notes.txt", "system.mp3"):
        (tmp_path / n).write_bytes(b"x")
    got = [p.name for p in slide_frames(tmp_path)]
    assert got == [
        "00010.png",
        "00020.png",          # auto before moved at the same second
        "00020_01.png",
        "00030_edit_01.png",  # annotated frames of second 30
        "00030_markiert_02.png",
    ]


def test_slide_frames_empty_for_no_slides(tmp_path):
    (tmp_path / "readme.txt").write_bytes(b"x")
    assert slide_frames(tmp_path) == []
