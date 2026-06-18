from core.playback import (
    SEEK_STEP_MS,
    SPEED_MAX_PCT,
    SPEED_MIN_PCT,
    seek_target,
    speed_percent_values,
)


def test_speed_values_range_and_step():
    vals = speed_percent_values()
    assert vals[0] == SPEED_MIN_PCT == 50
    assert vals[-1] == SPEED_MAX_PCT == 200
    assert 100 in vals and 200 in vals
    assert all(b - a == 10 for a, b in zip(vals, vals[1:]))


def test_seek_forward_and_back():
    assert seek_target(30_000, SEEK_STEP_MS, 120_000) == 40_000
    assert seek_target(30_000, -SEEK_STEP_MS, 120_000) == 20_000


def test_seek_clamps_at_zero():
    assert seek_target(5_000, -SEEK_STEP_MS, 120_000) == 0


def test_seek_clamps_at_duration():
    assert seek_target(115_000, SEEK_STEP_MS, 120_000) == 120_000


def test_seek_unknown_duration_not_clamped_high():
    # duration 0 (unknown) must not clamp a forward seek to 0
    assert seek_target(30_000, SEEK_STEP_MS, 0) == 40_000
