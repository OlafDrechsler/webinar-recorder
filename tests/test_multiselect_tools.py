"""Multi-select bulk move/delete across the three film-strip tools."""

import os

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.crop_out as co  # noqa: E402
import gui.sort_out as so  # noqa: E402
import player.play as pp  # noqa: E402
from gui.crop_out import CropWindow  # noqa: E402
from gui.sort_out import SortOutWindow  # noqa: E402
from player.play import Player  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _webinar(tmp_path, n=5):
    fol = tmp_path / "Webinar" / "folien"
    fol.mkdir(parents=True)
    for i in range(n):
        Image.fromarray(np.random.default_rng(i).integers(0, 256, (20, 30, 3), np.uint8), "RGB").save(
            str(fol / f"{i * 10:05d}.png")
        )
    return tmp_path / "Webinar", fol


def test_sorter_ctrl_shift_and_bulk_move(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    s = SortOutWindow()
    s._load_folder(_webinar(tmp_path, n=6)[0])
    s._action = "move"
    s._on_strip_click(1, Qt.ControlModifier)
    s._on_strip_click(3, Qt.ControlModifier)
    assert s._selection == {1, 3} and s._filmstrip._selected == {1, 3}
    s._on_strip_click(4, Qt.ShiftModifier)  # shift from anchor 3 -> {3,4}
    assert s._selection == {3, 4}
    s._remove_selected(move=True)
    fol = tmp_path / "Webinar" / "folien"
    assert sorted(p.name for p in (fol / "_aussortiert").glob("*.png")) == ["00030.png", "00040.png"]
    assert s._selection == set()
    # slide after the last selected one (00040) is framed & shown
    assert s._paths[s._ref_index].name == "00050.png"


def test_crop_bulk_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "ask_yes_no", lambda *a, **k: True)
    c = CropWindow()
    webinar, fol = _webinar(tmp_path)
    c._load_folder(webinar)
    c._on_strip_click(0, Qt.ControlModifier)
    c._on_strip_click(2, Qt.ControlModifier)
    assert c._selection == {0, 2}
    c._remove_selected(move=False)
    assert sorted(p.name for p in fol.glob("*.png")) == ["00010.png", "00030.png", "00040.png"]
    # slide after the last selected one (00020) is framed & shown
    assert c._paths[c._ref_index].name == "00030.png"


def test_crop_single_move_and_delete_menu_actions(tmp_path, monkeypatch):
    import gui.slide_ops as slide_ops
    monkeypatch.setattr(slide_ops, "ask_yes_no", lambda *a, **k: True)  # single delete confirm
    c = CropWindow()
    webinar, fol = _webinar(tmp_path)
    c._load_folder(webinar)
    c._remove_slide_at(1, move=True)  # single move
    assert (fol / "_aussortiert" / "00010.png").exists()
    c._remove_slide_at(1, move=False)  # single delete (index shifted)
    assert sorted(p.name for p in fol.glob("*.png")) == ["00000.png", "00030.png", "00040.png"]


def test_player_bulk_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "ask_yes_no", lambda *a, **k: True)
    webinar, fol = _webinar(tmp_path)
    p = Player()
    p.load_session(webinar)

    def item(name):
        return next(it for it in p._filmstrip._items if it.get("name") == name)

    p._on_frame_clicked(item("00000.png"), Qt.ControlModifier)
    p._on_frame_clicked(item("00020.png"), Qt.ControlModifier)
    assert p._selection == {"00000.png", "00020.png"}
    p._remove_selected(move=False)
    assert sorted(x.name for x in fol.glob("*.png")) == ["00010.png", "00030.png", "00040.png"]
    assert p._selection == set()
    # the slide right after the last selected one (00020) is framed & shown
    assert p._current_slide == "00030.png"
