import numpy as np

from core.slide_dedupe import (
    COMPARE,
    ELLIPSE,
    IGNORE,
    RECT,
    Region,
    build_compare_mask,
    masked_frames_differ,
    numeric_key,
    plan_deletions,
)


# ----- mask building -----
def test_ignore_rect_excludes_region():
    mask = build_compare_mask(10, 10, [Region(RECT, 2, 2, 3, 3)], IGNORE)
    assert mask.sum() == 100 - 9          # 3x3 block ignored
    assert not mask[2, 2] and not mask[4, 4]
    assert mask[0, 0]


def test_compare_rect_includes_only_region():
    mask = build_compare_mask(10, 10, [Region(RECT, 2, 2, 3, 3)], COMPARE)
    assert mask.sum() == 9
    assert mask[2, 2] and not mask[0, 0]


def test_compare_mode_without_regions_is_full():
    mask = build_compare_mask(10, 10, [], COMPARE)
    assert mask.all()


def test_ellipse_centre_in_corners_out():
    mask = build_compare_mask(20, 20, [Region(ELLIPSE, 0, 0, 20, 20)], IGNORE)
    assert not mask[10, 10]   # centre is inside the ellipse -> ignored
    assert mask[0, 0]         # corner is outside the ellipse -> still compared


# ----- masked difference -----
def _frame(fill=0):
    return np.full((40, 40, 3), fill, dtype=np.uint8)


def test_change_inside_ignored_region_is_not_a_difference():
    mask = build_compare_mask(40, 40, [Region(RECT, 0, 0, 20, 40)], IGNORE)
    base = _frame(0)
    changed = _frame(0)
    changed[:, 0:20] = 255  # bright block only in the ignored left half
    assert masked_frames_differ(base, changed, mask) is False


def test_change_outside_ignored_region_is_a_difference():
    mask = build_compare_mask(40, 40, [Region(RECT, 0, 0, 20, 40)], IGNORE)
    base = _frame(0)
    changed = _frame(0)
    changed[:, 20:40] = 255  # bright block in the compared right half
    assert masked_frames_differ(base, changed, mask) is True


def test_different_shapes_count_as_different():
    mask = build_compare_mask(40, 40, [], IGNORE)
    assert masked_frames_differ(_frame(0), np.zeros((30, 30, 3), np.uint8), mask) is True


# ----- numeric ordering -----
def test_numeric_key():
    assert numeric_key("00012.png") == 12
    assert numeric_key("00137_markiert_01.png") == 137


# ----- planning -----
def test_keeps_first_of_identical_run():
    mask = build_compare_mask(40, 40, [], IGNORE)
    a, b = _frame(0), _frame(255)
    frames = {"1": a, "2": a, "3": a, "4": b, "5": b}
    order = ["1", "2", "3", "4", "5"]
    removals = plan_deletions(order, lambda k: frames[k], mask)
    # First of each identical run kept (1 and 4); 2,3,5 removed.
    assert removals == ["2", "3", "5"]


def test_speaker_motion_ignored_keeps_single_slide():
    # Left half = "speaker" (changes every frame), right half = slide (constant).
    mask = build_compare_mask(40, 40, [Region(RECT, 0, 0, 20, 40)], IGNORE)
    frames = []
    for i in range(5):
        f = _frame(0)
        f[:, 0:20] = (i * 50) % 256   # speaker area churns
        frames.append(f)
    order = list(range(5))
    removals = plan_deletions(order, lambda k: frames[k], mask)
    # All identical outside the speaker area -> keep first, remove the other 4.
    assert removals == [1, 2, 3, 4]
