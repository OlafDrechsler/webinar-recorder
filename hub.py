"""WebinarOD launcher — the single entry point (see gui/hub.py).

Run:  python hub.py   (or use the "WebinarOD" shortcut created by install)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from core.i18n import init_language
from gui.branding import app_icon
from gui.hub import HubWindow


def main() -> int:
    # Exact display scale before QApplication (needed by the recorder's region
    # selector on high-DPI screens).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    init_language()
    hub = HubWindow()
    hub.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
