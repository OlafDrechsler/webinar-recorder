import numpy as np

from core.change_detection import frames_differ


def _solid(h, w, value, channels=3):
    return np.full((h, w, channels), value, dtype=np.uint8)


def test_identical_frames_do_not_differ():
    a = _solid(100, 100, 120)
    b = _solid(100, 100, 120)
    assert frames_differ(a, b) is False


def test_completely_different_frames_differ():
    a = _solid(100, 100, 0)
    b = _solid(100, 100, 255)
    assert frames_differ(a, b) is True


def test_different_shapes_count_as_change():
    # After a region resize the dimensions change; we must treat that as a change
    # (and the caller resets its baseline).
    a = _solid(100, 100, 120)
    b = _solid(120, 90, 120)
    assert frames_differ(a, b) is True


def test_tiny_noise_below_threshold_is_ignored():
    # A handful of pixels changed slightly (e.g. mouse cursor / compression noise)
    a = _solid(200, 200, 120)
    b = a.copy()
    b[0:5, 0:5] = 130  # 25 px out of 40000 = 0.06%
    assert frames_differ(a, b) is False


def test_small_real_change_is_detected():
    # A new bullet line appears: a thin band of pixels turns dark.
    a = _solid(200, 200, 255)
    b = a.copy()
    b[100:110, 10:190] = 0  # 1800 px out of 40000 = 4.5%
    assert frames_differ(a, b) is True


def test_thresholds_are_tunable():
    a = _solid(200, 200, 120)
    b = a.copy()
    b[0:20, 0:20] = 255  # 400 px = 1%, unmistakably changed per pixel
    # With a stricter fraction threshold this should NOT count as change.
    assert frames_differ(a, b, fraction_threshold=0.05) is False
    # With the sensitive default it should.
    assert frames_differ(a, b) is True


def test_scattered_compression_noise_is_suppressed_by_downscaling():
    # Simulates a re-encoded webinar video stream: the slide is unchanged but
    # ~3% of pixels jitter by a noticeable amount. Downscaling before comparing
    # must average this away so it does NOT register as a slide change.
    rng = np.random.default_rng(0)
    base = _solid(480, 640, 128)
    noisy = base.copy().astype(np.int16)
    mask = rng.random((480, 640)) < 0.03
    jitter = rng.integers(-25, 26, size=(480, 640))
    noisy[mask] += jitter[mask][:, None]
    noisy = np.clip(noisy, 0, 255).astype(np.uint8)
    assert frames_differ(base, noisy) is False


def test_real_change_still_detected_after_downscaling():
    # A whole region of a large frame changes (a new slide): must be detected.
    a = _solid(480, 640, 255)
    b = a.copy()
    b[100:300, 50:600] = 30  # large block changes
    assert frames_differ(a, b) is True
