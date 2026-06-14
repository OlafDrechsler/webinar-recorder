import numpy as np

from core.mic_gate import gate_mic_chunk


def test_enabled_passes_samples_through():
    chunk = np.array([100, -200, 300], dtype=np.int16)
    out = gate_mic_chunk(chunk, enabled=True)
    assert np.array_equal(out, chunk)


def test_disabled_returns_silence_same_shape_and_dtype():
    chunk = np.array([100, -200, 300], dtype=np.int16)
    out = gate_mic_chunk(chunk, enabled=False)
    assert np.array_equal(out, np.zeros(3, dtype=np.int16))
    assert out.dtype == chunk.dtype
    assert out.shape == chunk.shape


def test_disabled_does_not_mutate_input():
    chunk = np.array([100, -200, 300], dtype=np.int16)
    gate_mic_chunk(chunk, enabled=False)
    assert np.array_equal(chunk, np.array([100, -200, 300], dtype=np.int16))
