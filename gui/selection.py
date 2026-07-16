"""Ctrl/Shift multi-select logic for the film strips — pure, so it can be tested
without Qt. ``order`` is the list of selectable tokens in strip order (frame
indices for the sort/crop strips, slide names for the player strip)."""

from __future__ import annotations


def next_selection(order, selection, anchor, token, ctrl: bool, shift: bool):
    """Return ``(new_selection, new_anchor)`` after a click on ``token``.

    - Shift+click: select the contiguous run from the anchor to the token.
    - Ctrl+click: toggle the token, keeping the rest.
    - Plain click: select only the token.
    """
    if shift and anchor is not None and anchor in order and token in order:
        i, j = order.index(anchor), order.index(token)
        if i > j:
            i, j = j, i
        return set(order[i:j + 1]), anchor
    if ctrl:
        sel = set(selection)
        sel.discard(token) if token in sel else sel.add(token)
        return sel, token
    return {token}, token
