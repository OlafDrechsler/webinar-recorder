"""Keyboard shortcuts in the three film-strip tools:
←/→ step one slide, Entf = Aussortieren (verschieben), Shift+Entf = löschen."""

import os

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.crop_out as co  # noqa: E402
import gui.slide_ops as sops  # noqa: E402
import gui.sort_out as so  # noqa: E402
import player.play as pp  # noqa: E402
from gui.crop_out import CropWindow  # noqa: E402
from gui.sort_out import SortOutWindow  # noqa: E402
from player.play import Player  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _webinar(tmp_path, n=6):
    fol = tmp_path / "Webinar" / "folien"
    fol.mkdir(parents=True)
    for i in range(n):
        a = np.zeros((20, 30, 3), np.uint8)
        a[:] = (i * 10 % 256, 0, 0)
        Image.fromarray(a, "RGB").save(str(fol / f"{i * 10:05d}.png"))
    return tmp_path / "Webinar", fol


def _press(w, key, shift=False):
    mod = Qt.ShiftModifier if shift else Qt.NoModifier
    w.keyPressEvent(QKeyEvent(QEvent.KeyPress, key, mod))


def test_sorter_keyboard(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sops, "ask_yes_no", lambda *a, **k: True)
    webinar, fol = _webinar(tmp_path)
    s = SortOutWindow()
    s._load_folder(webinar)
    s._ref_index = 0
    _press(s, Qt.Key_Right)
    assert s._ref_index == 1
    _press(s, Qt.Key_Left)
    assert s._ref_index == 0
    # Shift+arrow starts & extends the marked range from the anchor
    _press(s, Qt.Key_Right, shift=True)
    _press(s, Qt.Key_Right, shift=True)
    assert s._selection == {0, 1, 2} and s._ref_index == 2
    _press(s, Qt.Key_Left)  # plain arrow clears the selection again
    assert s._selection == set()
    # Pos1/Ende jump to first/last slide
    _press(s, Qt.Key_End)
    assert s._ref_index == len(s._paths) - 1
    _press(s, Qt.Key_Home)
    assert s._ref_index == 0
    # Shift+Ende marks everything from the anchor to the last slide
    _press(s, Qt.Key_End, shift=True)
    assert s._selection == set(range(len(s._paths))) and s._ref_index == len(s._paths) - 1
    _press(s, Qt.Key_Home)  # plain Pos1 clears it and jumps to the first
    assert s._selection == set() and s._ref_index == 0
    _press(s, Qt.Key_Delete)  # Entf on 00000 -> move to _aussortiert
    assert (fol / "_aussortiert" / "00000.png").exists()
    cur = s._paths[s._ref_index].name
    _press(s, Qt.Key_Delete, shift=True)  # Shift+Entf -> permanent delete
    assert not (fol / cur).exists()
    assert not (fol / "_aussortiert" / cur).exists()


def test_crop_keyboard(tmp_path, monkeypatch):
    monkeypatch.setattr(co, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sops, "ask_yes_no", lambda *a, **k: True)
    webinar, fol = _webinar(tmp_path)
    c = CropWindow()
    c._load_folder(webinar)
    c._ref_index = 2
    _press(c, Qt.Key_Right)
    assert c._ref_index == 3
    _press(c, Qt.Key_Left, shift=True)  # extend the marked range
    assert c._selection == {2, 3} and c._ref_index == 2
    _press(c, Qt.Key_Right)  # plain arrow clears it and steps on
    assert c._selection == set() and c._ref_index == 3
    _press(c, Qt.Key_Home)  # Pos1 jumps to the first slide
    assert c._ref_index == 0
    _press(c, Qt.Key_End, shift=True)  # Shift+Ende marks through to the last
    assert c._selection == set(range(len(c._paths))) and c._ref_index == len(c._paths) - 1
    _press(c, Qt.Key_Home)  # plain Pos1 clears it
    assert c._selection == set() and c._ref_index == 0
    c._ref_index = 3
    _press(c, Qt.Key_Delete)  # move 00030
    assert (fol / "_aussortiert" / "00030.png").exists()
    cur = c._paths[c._ref_index].name
    _press(c, Qt.Key_Delete, shift=True)  # permanent delete
    assert not (fol / cur).exists()


def test_player_keyboard(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(sops, "ask_yes_no", lambda *a, **k: True)
    webinar, fol = _webinar(tmp_path)
    p = Player()
    p.load_session(webinar)
    p.show_slide("00010.png")
    _press(p, Qt.Key_Right)
    assert p._current_slide == "00020.png"
    _press(p, Qt.Key_Left)
    assert p._current_slide == "00010.png"
    # Shift+arrow starts & extends the marked range (by slide name)
    _press(p, Qt.Key_Right, shift=True)
    assert p._selection == {"00010.png", "00020.png"} and p._current_slide == "00020.png"
    _press(p, Qt.Key_Left)  # plain arrow clears it
    assert p._selection == set() and p._current_slide == "00010.png"
    # Pos1/Ende jump to first/last slide (by frame order)
    names = [f.name for f in p._frames]
    _press(p, Qt.Key_End)
    assert p._current_slide == names[-1]
    _press(p, Qt.Key_Home)
    assert p._current_slide == names[0]
    _press(p, Qt.Key_End, shift=True)  # Shift+Ende marks through to the last
    assert p._selection == set(names) and p._current_slide == names[-1]
    _press(p, Qt.Key_Home)  # plain Pos1 clears it
    assert p._selection == set() and p._current_slide == names[0]
    p.show_slide("00010.png")
    _press(p, Qt.Key_Delete)  # move current
    assert (fol / "_aussortiert" / "00010.png").exists()
    cur = p._current_slide
    _press(p, Qt.Key_Delete, shift=True)  # permanent delete
    assert not (fol / cur).exists()
