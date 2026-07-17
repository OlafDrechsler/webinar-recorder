"""core.discard: trim system track + delete slides/mic segments from a second."""

import pytest

from core.discard import count_from_second, discard_from_second


def _make(tmp_path, with_audio=False):
    web = tmp_path / "Web"
    fol = web / "folien"
    fol.mkdir(parents=True)
    mik = web / "mikro"
    mik.mkdir()
    for s in (5, 12, 30, 55):
        (fol / f"{s:05d}.png").write_bytes(b"x")
    (fol / "00030_edit_01.png").write_bytes(b"x")   # annotated at 30 -> counts as >=30
    for s in (8, 40):
        (mik / f"mikro_{s:06d}.wav").write_bytes(b"x")
    return web, fol, mik


def test_count_from_second(tmp_path):
    _web, fol, mik = _make(tmp_path)
    assert count_from_second(fol, mik, 30) == (3, 1)   # 30, 55, 30_edit ; mic@40
    assert count_from_second(fol, mik, 0) == (5, 2)
    assert count_from_second(fol, mik, 999) == (0, 0)


def test_discard_removes_slides_and_mics(tmp_path):
    web, fol, mik = _make(tmp_path)
    slides, mics = discard_from_second(web, fol, 30)
    assert (slides, mics) == (3, 1)
    assert sorted(p.name for p in fol.glob("*.png")) == ["00005.png", "00012.png"]
    assert sorted(p.name for p in mik.glob("*.wav")) == ["mikro_000008.wav"]


def test_discard_no_audio_track_is_safe(tmp_path):
    web, fol, mik = _make(tmp_path)   # no system.* present
    # should not raise even though there is no system track to trim
    slides, mics = discard_from_second(web, fol, 100)
    assert (slides, mics) == (0, 0)
