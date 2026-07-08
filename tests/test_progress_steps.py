"""The postprocessing reports analyse + convert as separate, ordered steps."""

from pathlib import Path

import app
import core.i18n as i18n


def _run_and_capture(monkeypatch, n_segments):
    # Stub out the actual FFmpeg work — we only check the reported steps.
    monkeypatch.setattr(app, "measure_loudness", lambda p: (-16.0, -1.0))
    monkeypatch.setattr(app, "compute_gain_db", lambda lufs, tp: 0.0)
    monkeypatch.setattr(app, "aggregate_mean_db", lambda xs: -16.0)
    monkeypatch.setattr(app, "transcode_to_mp3", lambda p, gain_db=0.0: p)

    events = []
    app._normalize_and_transcode(
        Path("system.wav"),
        [Path(f"mikro_{i}.wav") for i in range(n_segments)],
        progress=lambda label, done, total: events.append((label, done, total)),
    )
    return events


def test_system_only_reports_analyse_then_convert(monkeypatch):
    i18n._current = "de"
    events = _run_and_capture(monkeypatch, 0)
    labels = [e[0] for e in events]
    assert labels == [
        i18n.tr("progress.system_analyze"),
        i18n.tr("progress.system"),
        i18n.tr("progress.done"),
    ]
    # total = 2 (analyse + convert), counter increments 1, 2, then done at total
    assert [e[1] for e in events] == [1, 2, 2]
    assert all(e[2] == 2 for e in events)


def test_with_segments_counts_and_orders_all_phases(monkeypatch):
    i18n._current = "en"
    events = _run_and_capture(monkeypatch, 2)
    labels = [e[0] for e in events]
    assert labels[0] == i18n.tr("progress.system_analyze")
    assert labels[1] == i18n.tr("progress.system")
    # then analyse both segments, then convert both segments
    assert "Analysing mic segment 1/2" in labels[2]
    assert "Analysing mic segment 2/2" in labels[3]
    assert "Converting mic segment 1/2" in labels[4]
    assert "Converting mic segment 2/2" in labels[5]
    assert labels[6] == i18n.tr("progress.done")
    # total = 2 + 2*2 = 6, counter runs 1..6
    assert [e[1] for e in events] == [1, 2, 3, 4, 5, 6, 6]
    assert all(e[2] == 6 for e in events)
    i18n._current = "de"
