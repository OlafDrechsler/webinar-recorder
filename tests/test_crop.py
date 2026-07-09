"""Tests for core.crop (lossless batch cropping)."""

import numpy as np
from PIL import Image

from core.crop import clamp_box, crop_folder


def _img(path, w, h, seed=0):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)
    Image.fromarray(arr, "RGB").save(path)
    return arr


# ----- clamp_box -----
def test_clamp_within_bounds():
    assert clamp_box((10, 20, 100, 80), 200, 200) == (10, 20, 100, 80)


def test_clamp_to_image_edges():
    assert clamp_box((-5, -5, 500, 500), 200, 150) == (0, 0, 200, 150)


def test_clamp_empty_returns_none():
    assert clamp_box((300, 0, 400, 100), 200, 200) is None  # fully outside


# ----- crop_folder -----
def test_crop_is_lossless(tmp_path):
    arr = _img(tmp_path / "00010.png", 100, 60, seed=1)
    box = (20, 10, 80, 50)
    n = crop_folder(tmp_path, box, backup=False)
    assert n == 1
    out = np.asarray(Image.open(tmp_path / "00010.png").convert("RGB"))
    assert out.shape == (40, 60, 3)              # (h, w) = (50-10, 80-20)
    # every kept pixel is byte-for-byte identical to the original region
    assert np.array_equal(out, arr[10:50, 20:80])


def test_crop_all_slides_same_box(tmp_path):
    _img(tmp_path / "00010.png", 100, 60, seed=1)
    _img(tmp_path / "00020.png", 100, 60, seed=2)
    _img(tmp_path / "00020_edit_01.png", 100, 60, seed=3)  # annotated ones too
    n = crop_folder(tmp_path, (0, 0, 50, 60), backup=False)
    assert n == 3
    for name in ("00010.png", "00020.png", "00020_edit_01.png"):
        assert Image.open(tmp_path / name).size == (50, 60)


def test_backup_keeps_original(tmp_path):
    arr = _img(tmp_path / "00010.png", 100, 60, seed=1)
    crop_folder(tmp_path, (10, 10, 90, 50), backup=True)
    backup = tmp_path / "_original" / "00010.png"
    assert backup.exists()
    assert np.array_equal(np.asarray(Image.open(backup).convert("RGB")), arr)  # untouched


def test_backup_not_overwritten_on_second_crop(tmp_path):
    arr = _img(tmp_path / "00010.png", 100, 60, seed=1)
    crop_folder(tmp_path, (10, 10, 90, 50), backup=True)   # backup = true original
    crop_folder(tmp_path, (5, 5, 40, 30), backup=True)     # crops the already-cropped file
    backup = np.asarray(Image.open(tmp_path / "_original" / "00010.png").convert("RGB"))
    assert np.array_equal(backup, arr)  # still the very first original, full size


def test_full_box_is_noop(tmp_path):
    _img(tmp_path / "00010.png", 100, 60, seed=1)
    n = crop_folder(tmp_path, (0, 0, 100, 60), backup=False)
    assert n == 0  # box == whole image -> nothing changed
    assert Image.open(tmp_path / "00010.png").size == (100, 60)


def test_progress_reports_total(tmp_path):
    _img(tmp_path / "00010.png", 40, 40)
    _img(tmp_path / "00020.png", 40, 40)
    seen = []
    crop_folder(tmp_path, (0, 0, 20, 20), backup=False, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (2, 2)          # ends at total/total
    assert all(t == 2 for _, t in seen)
