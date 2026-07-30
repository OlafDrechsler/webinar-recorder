"""core.discard: trim system track + delete slides/mic segments from a second."""

import pytest

from core.discard import (
    count_before_second,
    count_from_second,
    discard_before_second,
    discard_from_second,
)


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


# ----- discard the BEGINNING (renumber survivors to start at 0) -----

def test_count_before_second(tmp_path):
    _web, fol, mik = _make(tmp_path)
    # at t=12 the slide visible is @12 (base); only @5 is before it -> removed.
    # mic@8 ends before 12 (dummy -> duration unknown -> treated fully-before);
    # mic@40 starts after 12 -> kept.
    assert count_before_second(fol, mik, 12) == (1, 1)
    assert count_before_second(fol, mik, 0) == (0, 0)   # nothing before the first slide


def test_discard_before_renumbers_slides_and_mics(tmp_path):
    web, fol, mik = _make(tmp_path)
    slides, mics = discard_before_second(web, fol, 12)
    assert (slides, mics) == (1, 1)
    # @5 dropped; @12 -> 0, @30 -> 18, @55 -> 43, @30_edit -> 18_edit (suffix kept)
    assert sorted(p.name for p in fol.glob("*.png")) == [
        "00000.png", "00018.png", "00018_edit_01.png", "00043.png",
    ]
    # mic@8 dropped, mic@40 -> 40-12 = 28
    assert sorted(p.name for p in mik.glob("*.wav")) == ["mikro_000028.wav"]


def test_discard_before_zero_keeps_everything(tmp_path):
    web, fol, mik = _make(tmp_path)
    slides, mics = discard_before_second(web, fol, 0)
    assert (slides, mics) == (0, 0)
    assert sorted(p.name for p in fol.glob("*.png")) == [
        "00005.png", "00012.png", "00030.png", "00030_edit_01.png", "00055.png",
    ]
    assert sorted(p.name for p in mik.glob("*.wav")) == ["mikro_000008.wav", "mikro_000040.wav"]


def test_discard_before_no_audio_track_is_safe(tmp_path):
    web, fol, mik = _make(tmp_path)   # no system.* present -> renumber still works
    slides, mics = discard_before_second(web, fol, 12)
    assert (slides, mics) == (1, 1)
