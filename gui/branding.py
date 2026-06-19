"""Product name and app icon, shared by all windows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

APP_NAME = "WebinarOD"

_ICON_PNG = Path(__file__).resolve().parent.parent / "assets" / "icon.png"


def app_icon() -> QIcon:
    """The WebinarOD window/taskbar icon (empty QIcon if the file is missing)."""
    return QIcon(str(_ICON_PNG)) if _ICON_PNG.exists() else QIcon()
