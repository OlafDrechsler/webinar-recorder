"""Headless flow test for the crop tool window (gui.crop_out)."""

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.crop_out import CropWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _make_folder(tmp_path):
    fol = tmp_path / "Webinar" / "folien"
    fol.mkdir(parents=True)
    for s in (10, 20, 30):
        arr = np.random.default_rng(s).integers(0, 256, size=(60, 100, 3), dtype=np.uint8)
        Image.fromarray(arr, "RGB").save(str(fol / f"{s:05d}.png"))
    return tmp_path / "Webinar", fol


def test_start_disabled_until_area_marked(tmp_path):
    webinar, _ = _make_folder(tmp_path)
    w = CropWindow()
    w._load_folder(webinar)  # resolves into folien
    assert [p.name for p in w._paths] == ["00010.png", "00020.png", "00030.png"]
    assert w._start_btn.isEnabled() is False
    w._canvas._box = [25, 10, 90, 55]
    w._canvas.box_changed.emit()
    assert w._start_btn.isEnabled() is True
    assert "65" in w._hint.text() and "45" in w._hint.text()


def test_box_persists_while_browsing(tmp_path):
    webinar, _ = _make_folder(tmp_path)
    w = CropWindow()
    w._load_folder(webinar)
    w._canvas._box = [10, 5, 80, 50]
    w._canvas.box_changed.emit()
    w._step_ref(1)
    w._step_ref(1)
    assert w._canvas.keep_box() == (10, 5, 80, 50)


def test_crop_keeps_originals_and_reloads(tmp_path):
    webinar, fol = _make_folder(tmp_path)
    w = CropWindow()
    w._load_folder(webinar)
    w._canvas._box = [25, 10, 90, 55]
    w._canvas.box_changed.emit()
    w._backup = True
    w._start()
    for name in ("00010.png", "00020.png", "00030.png"):
        assert Image.open(fol / name).size == (65, 45)
        assert (fol / "_original" / name).exists()
    assert w._start_btn.isEnabled() is False  # rectangle cleared after cropping
    assert w._canvas._pix.width() == 65        # reference reloaded to cropped size


def test_mode_toggle(tmp_path):
    webinar, _ = _make_folder(tmp_path)
    w = CropWindow()
    w._load_folder(webinar)
    assert w._backup is True
    w._toggle_mode()
    assert w._backup is False
    w._toggle_mode()
    assert w._backup is True
