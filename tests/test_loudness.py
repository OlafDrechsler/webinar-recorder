import math

from core.loudness import DEFAULT_TARGET_DB, aggregate_mean_db, compute_gain_db


def test_quiet_track_is_boosted_to_target():
    # mean -30 dB, no peak limit -> raise by 12 dB to reach -18.
    assert compute_gain_db(-30.0, peak_db=None, target_db=-18.0) == 12.0


def test_loud_track_is_attenuated():
    assert compute_gain_db(-5.0, peak_db=-1.0, target_db=-18.0) == -13.0


def test_gain_capped_to_avoid_clipping():
    # Wants +12 dB, but peak is already -2 dB; ceiling -1 dB allows only +1 dB.
    assert compute_gain_db(-30.0, peak_db=-2.0, target_db=-18.0, ceiling_db=-1.0) == 1.0


def test_attenuation_not_limited_by_ceiling():
    # Lowering volume never clips, so the ceiling must not block a negative gain.
    assert compute_gain_db(-2.0, peak_db=-0.1, target_db=-18.0, ceiling_db=-1.0) == -16.0


def test_missing_measurement_means_no_gain():
    assert compute_gain_db(None) == 0.0


def test_aggregate_none_when_empty():
    assert aggregate_mean_db([]) is None
    assert aggregate_mean_db([None, None]) is None


def test_aggregate_equal_levels():
    assert aggregate_mean_db([-20.0, -20.0]) == -20.0


def test_aggregate_is_power_weighted_toward_louder():
    # Combining -10 and -30 dB should sit near the louder one (~ -13 dB), not the
    # arithmetic mean (-20 dB).
    result = aggregate_mean_db([-10.0, -30.0])
    assert result is not None
    assert math.isclose(result, -12.99, abs_tol=0.1)


def test_default_target_is_reasonable():
    assert -24.0 <= DEFAULT_TARGET_DB <= -12.0
