"""Window title / folder-header consistency across Player, sort-out and crop."""

import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.i18n import tr  # noqa: E402
from gui.sort_out import webinar_name  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ----- webinar_name (pure) -----
def test_webinar_name_uses_parent_for_folien():
    assert webinar_name(Path("/x/Webinar_A/folien")) == "Webinar_A"


def test_webinar_name_uses_own_name_otherwise():
    assert webinar_name(Path("/x/my_slides")) == "my_slides"


def _webinar(tmp_path):
    fol = tmp_path / "Webinar_2026" / "folien"
    fol.mkdir(parents=True)
    for s in (5, 12, 30):
        Image.fromarray(np.random.default_rng(s).integers(0, 256, (30, 40, 3), np.uint8), "RGB").save(
            str(fol / f"{s:05d}.png")
        )
    return tmp_path / "Webinar_2026"


# ----- titles are "WebinarOD – <toolname>" (no folder appended) -----
def test_player_title_and_folder(tmp_path):
    from player.play import Player

    p = Player()
    assert p.windowTitle() == f"WebinarOD – {tr('hub.player')}"
    p.load_session(_webinar(tmp_path))
    assert p.windowTitle() == f"WebinarOD – {tr('hub.player')}"   # unchanged by loading
    assert p._path_lbl.text() == "Webinar_2026"                  # webinar name, not "folien"
    assert hasattr(p, "_strip_left") and hasattr(p, "_strip_right")


def test_sort_title_and_folder(tmp_path):
    from gui.sort_out import SortOutWindow

    s = SortOutWindow()
    assert s.windowTitle() == f"WebinarOD – {tr('hub.sort')}"
    s._load_folder(_webinar(tmp_path))
    assert s.windowTitle() == f"WebinarOD – {tr('hub.sort')}"
    assert s._path_lbl.text() == "Webinar_2026"
    assert s._filmstrip._browse is True


def test_crop_title_and_folder(tmp_path):
    from gui.crop_out import CropWindow

    c = CropWindow()
    assert c.windowTitle() == f"WebinarOD – {tr('hub.crop')}"
    c._load_folder(_webinar(tmp_path))
    assert c.windowTitle() == f"WebinarOD – {tr('hub.crop')}"
    assert c._path_lbl.text() == "Webinar_2026"


# ----- clicking a strip frame shows it big AND centres it (browse tools) -----
def test_sort_click_centres(tmp_path):
    from gui.sort_out import SortOutWindow

    s = SortOutWindow()
    s._load_folder(_webinar(tmp_path))
    s._on_strip_click(2)
    assert s._ref_index == 2 and s._filmstrip._effective_center() == 2


def test_player_step_slide(tmp_path):
    from player.play import Player

    p = Player()
    p.load_session(_webinar(tmp_path))
    p.show_slide("00005.png")
    p._step_slide(1)
    assert p._current_slide == "00012.png"
    p._step_slide(-1)
    assert p._current_slide == "00005.png"
