import numpy as np

from core.capture_state import CaptureState


def _solid(value, h=50, w=50):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_first_frame_is_always_saved():
    state = CaptureState()
    assert state.consider(_solid(120)) is True


def test_identical_following_frame_not_saved():
    state = CaptureState()
    state.consider(_solid(120))
    assert state.consider(_solid(120)) is False


def test_changed_frame_is_saved_and_becomes_new_baseline():
    state = CaptureState()
    state.consider(_solid(120))
    assert state.consider(_solid(0)) is True
    # Baseline is now the dark frame; another dark frame should not save.
    assert state.consider(_solid(0)) is False


def test_marked_save_does_not_change_baseline():
    # Step 7: a manual annotated save must NOT become the comparison baseline.
    state = CaptureState()
    state.consider(_solid(120))            # baseline = 120
    state.note_marked_save(_solid(0))      # a wildly different annotated frame
    # An auto frame identical to the real baseline must still be skipped.
    assert state.consider(_solid(120)) is False


def test_reset_after_region_change_forces_next_save():
    state = CaptureState()
    state.consider(_solid(120))
    state.reset()
    # Even the same-looking frame is saved again because baseline was cleared.
    assert state.consider(_solid(120)) is True
