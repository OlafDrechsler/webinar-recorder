"""Pure Ctrl/Shift multi-select logic (gui.selection.next_selection)."""

from gui.selection import next_selection

ORDER = [0, 1, 2, 3, 4]


def test_plain_click_selects_one():
    assert next_selection(ORDER, {2, 3}, 2, 4, ctrl=False, shift=False) == ({4}, 4)


def test_ctrl_click_adds():
    assert next_selection(ORDER, {1}, 1, 3, ctrl=True, shift=False) == ({1, 3}, 3)


def test_ctrl_click_toggles_off():
    assert next_selection(ORDER, {1, 3}, 3, 3, ctrl=True, shift=False) == ({1}, 3)


def test_shift_selects_range_from_anchor():
    sel, anchor = next_selection(ORDER, {1}, 1, 4, ctrl=False, shift=True)
    assert sel == {1, 2, 3, 4} and anchor == 1


def test_shift_range_backwards():
    sel, anchor = next_selection(ORDER, set(), 3, 1, ctrl=False, shift=True)
    assert sel == {1, 2, 3} and anchor == 3


def test_shift_without_anchor_is_plain():
    assert next_selection(ORDER, set(), None, 2, ctrl=False, shift=True) == ({2}, 2)


def test_works_with_string_tokens():
    order = ["a.png", "b.png", "c.png"]
    sel, anchor = next_selection(order, set(), "a.png", "c.png", ctrl=False, shift=True)
    assert sel == {"a.png", "b.png", "c.png"} and anchor == "a.png"
