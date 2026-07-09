"""Partial-range action (Aktion ab/bis hier) for sort-out and crop, plus the
red-toggle CAPS and crop cursor tweaks."""

import os

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.crop_out as co  # noqa: E402
import gui.sort_out as so  # noqa: E402
from core.i18n import tr  # noqa: E402
from gui.crop_out import CropCanvas, CropWindow  # noqa: E402
from gui.sort_out import SortOutWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _webinar(tmp_path, n=5):
    fol = tmp_path / "Webinar" / "folien"
    fol.mkdir(parents=True)
    for i in range(n):
        Image.fromarray(np.random.default_rng(i).integers(0, 256, (40, 60, 3), np.uint8), "RGB").save(
            str(fol / f"{i * 10:05d}.png")
        )
    return tmp_path / "Webinar", fol


# ----- Point 2: red toggle text is CAPS -----
def test_sort_delete_toggle_is_caps():
    s = SortOutWindow()
    s._action = "delete"
    s._refresh_mode_labels()
    assert s._action_btn.text() == tr("sort.action_delete").upper()


def test_crop_overwrite_toggle_is_caps():
    c = CropWindow()
    c._backup = False
    c._refresh_mode_btn()
    assert c._mode_btn.text() == tr("crop.mode_overwrite").upper()


# ----- Point 3: crop canvas cursor is not a crosshair -----
def test_crop_cursor_not_crosshair():
    assert CropCanvas().cursor().shape() != Qt.CrossCursor


# ----- Point 4: sort range -----
def test_sort_effective_range_and_highlight(tmp_path):
    s = SortOutWindow()
    s._load_folder(_webinar(tmp_path)[0])
    s._range_start, s._range_end = 3, 1  # given in any order
    s._apply_range_highlight()
    assert s._effective_range() == (1, 3)         # normalised
    assert s._filmstrip._range == (1, 3)          # highlighted


def test_sort_run_uses_range_and_first_is_reference(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(so.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    s = SortOutWindow()
    s._action = "move"
    s._load_folder(_webinar(tmp_path)[0])
    s._range_start, s._range_end = 1, 3
    s._apply_range_highlight()
    s._ref_index = 2  # inside the range
    s._run()
    assert s._running
    assert s._filmstrip._history == [1] and s._filmstrip._upcoming == [2, 3]
    assert s._ref_index == 1  # first slide of the range became the reference
    s._cancel_run()
    assert s._range_start is None and s._filmstrip._range is None  # cleared


def test_sort_warns_when_reference_outside_range(tmp_path, monkeypatch):
    monkeypatch.setattr(so.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: False)  # decline the warning
    s = SortOutWindow()
    s._action = "move"
    s._load_folder(_webinar(tmp_path)[0])
    s._range_start, s._range_end = 3, 4
    s._apply_range_highlight()
    s._ref_index = 0  # outside the range
    s._run()
    assert not s._running  # aborted by the outside-range warning


# ----- Point 4: crop range -----
def test_crop_only_crops_selected_range(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "ask_yes_no", lambda *a, **k: True)
    c = CropWindow()
    wdir, fol = _webinar(tmp_path)
    c._load_folder(wdir)
    c._range_start, c._range_end = 1, 2
    c._apply_range_highlight()
    assert c._filmstrip._range == (1, 2)
    c._canvas._box = [10, 5, 50, 35]
    c._canvas.box_changed.emit()
    c._ref_index = 1
    c._backup = True
    c._start()
    assert Image.open(fol / "00010.png").size == (40, 30)
    assert Image.open(fol / "00020.png").size == (40, 30)
    for name in ("00000.png", "00030.png", "00040.png"):
        assert Image.open(fol / name).size == (60, 40)  # untouched
    assert c._range_start is None  # cleared after cropping
