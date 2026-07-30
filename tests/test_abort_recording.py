"""Aufnahme abbrechen: der Abbrechen-Button und der X-Dialog verwerfen die
Session ohne Nachbearbeitung, der Beenden-Weg speichert und verarbeitet weiter."""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import gui.control_window as cw  # noqa: E402
from gui.control_window import ControlWindow  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeMic:
    """Stand-in for SegmentedMicRecorder — opens no audio device."""

    def __init__(self, *a, **k):
        self.segments: list = []
        self.is_active = False

    def start_monitor(self):
        pass

    def set_out_dir(self, d):
        pass

    def set_mic_mode(self, m):
        pass

    def enable_recording(self, t):
        pass

    def stop(self):
        pass


class _FakeSystem:
    """Stand-in for SystemAudioRecorder — start() just creates system.wav."""

    def __init__(self, path):
        self._path = path

    def start(self):
        self._path.write_bytes(b"RIFF0000")  # pretend a real recording exists

    def stop(self):
        pass


def _make(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "SegmentedMicRecorder", _FakeMic)
    monkeypatch.setattr(cw, "SystemAudioRecorder", _FakeSystem)
    calls: list = []
    w = ControlWindow(None, lambda wav, segs: calls.append((wav, segs)))
    w._base = tmp_path  # keep the session inside tmp, never the real data dir
    return w, calls


def test_abort_button_deletes_session_and_skips_processing(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "ask_yes_no", lambda *a, **k: True)
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    session = w._session
    assert session.exists() and (session / "folien").exists()
    w._abort_recording()  # confirmed -> discard
    assert not session.exists()
    assert calls == []  # no post-processing


def test_abort_button_cancelled_keeps_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(cw, "ask_yes_no", lambda *a, **k: False)  # user says "Nein"
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    w._abort_recording()
    assert w._session.exists() and w._recording  # nothing happened


def test_stop_button_saves_and_keeps_session(tmp_path, monkeypatch):
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    session = w._session
    w._toggle_recording()  # recording -> stop & save
    assert session.exists()
    assert len(calls) == 1  # post-processing ran


def test_x_dialog_cancel_keeps_recording(tmp_path, monkeypatch):
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    session = w._session
    monkeypatch.setattr(cw, "ask_save_discard_cancel", lambda *a, **k: "cancel")
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert not ev.isAccepted()  # close was vetoed
    assert session.exists() and w._recording and calls == []


def test_x_dialog_discard_deletes_session(tmp_path, monkeypatch):
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    session = w._session
    monkeypatch.setattr(cw, "ask_save_discard_cancel", lambda *a, **k: "discard")
    w.closeEvent(QCloseEvent())
    assert not session.exists() and calls == []


def test_x_dialog_save_processes(tmp_path, monkeypatch):
    w, calls = _make(tmp_path, monkeypatch)
    w._start_recording()
    session = w._session
    monkeypatch.setattr(cw, "ask_save_discard_cancel", lambda *a, **k: "save")
    w.closeEvent(QCloseEvent())
    assert session.exists() and len(calls) == 1
