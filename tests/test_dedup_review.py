"""New dedup flow: the run MARKS duplicates (red), nothing is applied until the
user runs 'Aktion ausfuehren'. Marks are reviewable and toggleable."""

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
    a = np.zeros((30, 40, 3), np.uint8)
    a[:] = color
    return a


def _run_to_end(s):
    s._run()
    guard = 0
    while s._running and guard < 200:
        s._do_phase()
        guard += 1


def _sorter(tmp_path, monkeypatch):
    monkeypatch.setattr(so.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(so, "ask_yes_no", lambda *a, **k: True)
    fol = tmp_path / "Web" / "folien"
    fol.mkdir(parents=True)
    # 0 blue | 1,2 red(dups) | 3 green | 4 green(dup)
    for i, c in {0: (0, 0, 255), 1: (255, 0, 0), 2: (255, 0, 0), 3: (0, 255, 0), 4: (0, 255, 0)}.items():
        Image.fromarray(_solid(c), "RGB").save(str(fol / f"{i * 10:05d}.png"))
    s = SortOutWindow()
    s._load_folder(tmp_path / "Web")
    s._action = "move"
    return s, fol


def test_run_only_marks_nothing_applied(tmp_path, monkeypatch):
    s, fol = _sorter(tmp_path, monkeypatch)
    assert not s._exec_btn.isEnabled()  # dimmed before a run
    _run_to_end(s)
    assert s._marked == {"00020.png", "00040.png"}
    assert len(list(fol.glob("*.png"))) == 5     # nothing moved/deleted yet
    assert not (fol / "_aussortiert").exists()
    assert s._exec_btn.isEnabled()


def test_execute_applies_marks(tmp_path, monkeypatch):
    s, fol = _sorter(tmp_path, monkeypatch)
    _run_to_end(s)
    s._execute_marked()
    assert sorted(p.name for p in fol.glob("*.png")) == ["00000.png", "00010.png", "00030.png"]
    assert sorted(p.name for p in (fol / "_aussortiert").glob("*.png")) == ["00020.png", "00040.png"]
    assert s._marked == set() and not s._exec_btn.isEnabled()


def test_toggle_mark_flips_single(tmp_path, monkeypatch):
    s, fol = _sorter(tmp_path, monkeypatch)
    _run_to_end(s)
    idx10 = next(i for i, p in enumerate(s._paths) if p.name == "00010.png")
    s._toggle_mark(idx10)                       # make a kept baseline a duplicate
    assert "00010.png" in s._marked
    s._toggle_mark(idx10)                       # and back
    assert "00010.png" not in s._marked


def test_cancel_run_drops_marks(tmp_path, monkeypatch):
    s, fol = _sorter(tmp_path, monkeypatch)
    s._run()
    s._do_phase()  # one step, some progress
    s._cancel_run()
    assert not s._running and s._marked == set()
    assert not s._exec_btn.isEnabled()
    assert len(list(fol.glob("*.png"))) == 5


def test_marks_survive_single_delete_by_name(tmp_path, monkeypatch):
    s, fol = _sorter(tmp_path, monkeypatch)
    _run_to_end(s)                              # marks 00020, 00040
    # delete an unrelated slide (00000) -> indices shift, marks (by name) stay valid
    idx0 = next(i for i, p in enumerate(s._paths) if p.name == "00000.png")
    s._remove_slide_at(idx0, move=True)
    assert s._marked == {"00020.png", "00040.png"}
    s._execute_marked()
    assert not (fol / "00020.png").exists() and not (fol / "00040.png").exists()
