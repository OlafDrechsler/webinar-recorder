"""Persistent user settings — currently just the storage location.

Why this exists: the program may be installed read-only under
``C:\\Program Files`` on several machines, while the recordings should land in a
completely different place (typically a OneDrive-synced folder shared between
those machines). So we cannot store the chosen data folder next to the program.

Instead the settings file lives in the per-user app-data directory
(``%APPDATA%\\WebinarRecorder\\settings.json``). The data folder the user picks
once is remembered there and pre-filled on the next launch.

Everything here is plain file/JSON logic with no GUI, so it is unit-tested. The
config location can be redirected via the ``WEBINAR_RECORDER_CONFIG`` environment
variable (used by the tests to avoid touching the real profile).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "WebinarRecorder"
_DATA_DIR_KEY = "data_dir"
_WORK_AREA_KEY = "work_area_geometry"
_MIC_DEVICE_KEY = "mic_device"
_PLAYER_VOL_KEY = "player_volumes"
_SORTOUT_KEY = "sortout_config"


def config_path() -> Path:
    """Absolute path of the settings JSON file.

    Honours ``WEBINAR_RECORDER_CONFIG`` first (tests/power users), otherwise uses
    ``%APPDATA%`` and finally the home directory as a last resort.
    """
    override = os.environ.get("WEBINAR_RECORDER_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME / "settings.json"


def load_settings() -> dict:
    """Read the settings dict; return {} if the file is missing or corrupt."""
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_settings(settings: dict) -> None:
    """Write the settings dict, creating the parent folder if needed."""
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def default_data_dir() -> Path:
    """First-launch fallback when nothing has been chosen yet."""
    return Path.home() / "Documents" / APP_NAME


def get_data_dir() -> Path:
    """The remembered data folder, or the default if none was saved yet."""
    stored = load_settings().get(_DATA_DIR_KEY)
    return Path(stored) if stored else default_data_dir()


def set_data_dir(path: str | os.PathLike) -> None:
    """Remember ``path`` as the data folder for future launches."""
    settings = load_settings()
    settings[_DATA_DIR_KEY] = str(path)
    save_settings(settings)


def get_work_area_geometry() -> tuple[int, int, int, int] | None:
    """Last (x, y, width, height) of the work-area window, or None if unset."""
    geom = load_settings().get(_WORK_AREA_KEY)
    if isinstance(geom, dict) and all(k in geom for k in ("x", "y", "w", "h")):
        try:
            return (int(geom["x"]), int(geom["y"]), int(geom["w"]), int(geom["h"]))
        except (TypeError, ValueError):
            return None
    return None


def set_work_area_geometry(x: int, y: int, w: int, h: int) -> None:
    """Remember the work-area window's position and size for next time."""
    settings = load_settings()
    settings[_WORK_AREA_KEY] = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
    save_settings(settings)


def get_mic_device() -> str | None:
    """The microphone device name the user picked last, or None (auto-select)."""
    value = load_settings().get(_MIC_DEVICE_KEY)
    return value if isinstance(value, str) and value else None


def set_mic_device(name: str) -> None:
    """Remember the chosen microphone (by name; survives index changes)."""
    settings = load_settings()
    settings[_MIC_DEVICE_KEY] = str(name)
    save_settings(settings)


def _clamp_pct(value, fallback: int) -> int:
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return fallback


def get_player_volumes() -> tuple[int, int]:
    """Saved (system, mic) playback volumes in percent (0..100). Default 100/100."""
    data = load_settings().get(_PLAYER_VOL_KEY)
    if isinstance(data, dict):
        return (_clamp_pct(data.get("system"), 100), _clamp_pct(data.get("mic"), 100))
    return (100, 100)


def set_player_volumes(system_pct: int, mic_pct: int) -> None:
    """Remember the playback volumes for system and mic."""
    settings = load_settings()
    settings[_PLAYER_VOL_KEY] = {
        "system": _clamp_pct(system_pct, 100),
        "mic": _clamp_pct(mic_pct, 100),
    }
    save_settings(settings)


def get_sortout_config() -> dict | None:
    """Last-used mask/threshold for the slide-deduplication tool, or None."""
    data = load_settings().get(_SORTOUT_KEY)
    return data if isinstance(data, dict) else None


def set_sortout_config(config: dict) -> None:
    """Remember the slide-deduplication mask/threshold for next time."""
    settings = load_settings()
    settings[_SORTOUT_KEY] = config
    save_settings(settings)
