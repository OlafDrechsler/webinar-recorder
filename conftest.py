import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def _isolate_settings(tmp_path, monkeypatch):
    """Redirect the settings file to a per-test temp path so tests never read or
    write the real ``%APPDATA%\\WebinarRecorder\\settings.json``."""
    monkeypatch.setenv("WEBINAR_RECORDER_CONFIG", str(tmp_path / "settings.json"))
