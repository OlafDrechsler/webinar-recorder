"""During a dedup run annotated frames are always kept, but a duplicate that
follows one is still detected (compared against the previous real slide)."""

import os

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.sort_out as so  # noqa: E402
from gui.sort_out import SortOutWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _solid(color):
    a = np.zeros((40, 60, 3), np.uint8)
    a[:] = color
    return a


def test_annotated_kept_and_following_duplicate_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(so.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    fol = tmp_path / "Webinar" / "folien"
    fol.mkdir(parents=True)
    # 10 blue | 20 red | 20_edit red (annotated, must stay) | 30 red (dup of 20 -> go)
    Image.fromarray(_solid((0, 0, 255)), "RGB").save(str(fol / "00010.png"))
    Image.fromarray(_solid((255, 0, 0)), "RGB").save(str(fol / "00020.png"))
    Image.fromarray(_solid((255, 0, 0)), "RGB").save(str(fol / "00020_edit_01.png"))
    Image.fromarray(_solid((255, 0, 0)), "RGB").save(str(fol / "00030.png"))

    s = SortOutWindow()
    s._load_folder(tmp_path / "Webinar")
    s._action = "move"  # set after load (config may override in __init__ path)
    s._run()
    guard = 0
    while s._running and guard < 100:
        s._do_phase()
        guard += 1

    # only the following duplicate is marked; the annotated frame is never marked
    assert s._marked == {"00030.png"}
    s._execute_marked()
    remaining = sorted(p.name for p in fol.glob("*.png"))
    assert remaining == ["00010.png", "00020.png", "00020_edit_01.png"]
    assert (fol / "_aussortiert" / "00030.png").exists()


def test_annotated_frame_never_in_removals_even_if_duplicate(tmp_path, monkeypatch):
    monkeypatch.setattr(so.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    fol = tmp_path / "W" / "folien"
    fol.mkdir(parents=True)
    # auto + its exact annotated twin at the same second: the annotated one stays.
    Image.fromarray(_solid((10, 20, 30)), "RGB").save(str(fol / "00005.png"))
    Image.fromarray(_solid((10, 20, 30)), "RGB").save(str(fol / "00005_markiert_01.png"))
    s = SortOutWindow()
    s._load_folder(tmp_path / "W")
    s._action = "move"
    s._run()
    guard = 0
    while s._running and guard < 100:
        s._do_phase()
        guard += 1
    assert s._marked == set()  # annotated twin is never marked as a duplicate
    s._execute_marked()
    assert (fol / "00005_markiert_01.png").exists()  # annotated kept despite being identical
    assert not (fol / "_aussortiert").exists()
