"""'Aufnahme ab aktueller Zeit verwerfen' in the player trims the system track
AND deletes every slide (+ mic segment) after the playhead; the slide shown at
the cut is kept."""

import os

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import player.play as pp  # noqa: E402
from player.play import Player  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _session(tmp_path, n=5):
    session = tmp_path / "Webinar"
    fol = session / "folien"
    fol.mkdir(parents=True)
    for i in range(n):
        Image.fromarray(np.zeros((20, 30, 3), np.uint8), "RGB").save(str(fol / f"{i * 10:05d}.png"))
    (session / "system.wav").write_bytes(b"RIFF....WAVE")  # only its existence matters here
    return session, fol


def test_player_discard_deletes_trailing_slides(tmp_path, monkeypatch):
    monkeypatch.setattr(pp, "ask_yes_no", lambda *a, **k: True)
    monkeypatch.setattr(pp, "trim_audio", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_wait_file_writable", lambda *a, **k: True)
    # Run the worker synchronously instead of on a QThread.
    monkeypatch.setattr(Player, "_run_with_progress", lambda self, label, worker: worker.run())

    session, fol = _session(tmp_path)
    p = Player()
    p.load_session(session)
    p._discard_from_here(25000)  # playhead at 25 s

    # slides at seconds 30 and 40 are gone; 0/10/20 (at or before the cut) stay
    assert sorted(x.name for x in fol.glob("*.png")) == ["00000.png", "00010.png", "00020.png"]
