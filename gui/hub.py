"""WebinarOD hub: the single launcher window.

One window (one shortcut, the neutral brand name) from which the three tools are
opened — Aufnahme, Player, Folien aussortieren — plus Einstellungen with the
language selection. The hub stays open; each tool can be open once at a time
(re-clicking raises it). Closing the hub quits the whole app (with a warning if a
recording is in progress). Tools run in this single process, so the chosen
language applies to everything.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import app as recorder
from core.i18n import LANGUAGES, current_language, set_current_language, tr
from gui.branding import APP_NAME, app_icon
from gui.dialogs import ask_yes_no
from gui.sort_out import open_sorter
from player.play import open_player


class SettingsDialog(QDialog):
    def __init__(self, parent: "HubWindow") -> None:
        super().__init__(parent)
        self.setWindowIcon(app_icon())
        self._parent = parent
        self.setWindowTitle(tr("hub.settings"))

        self._lang_label = QLabel(tr("settings.language"))
        self._combo = QComboBox()
        for code, name in LANGUAGES.items():
            self._combo.addItem(name, code)
        self._combo.setCurrentIndex(list(LANGUAGES).index(current_language()))
        self._combo.currentIndexChanged.connect(self._on_language)

        self._hint = QLabel(tr("settings.hint"))
        self._hint.setStyleSheet("color:#888;")
        self._close = QPushButton(tr("common.close"))
        self._close.clicked.connect(self.accept)

        row = QHBoxLayout()
        row.addWidget(self._lang_label)
        row.addWidget(self._combo, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self._hint)
        layout.addWidget(self._close)
        self.resize(360, 130)

    def _on_language(self) -> None:
        set_current_language(self._combo.currentData())
        # Retranslate this dialog and the hub immediately.
        self.setWindowTitle(tr("hub.settings"))
        self._lang_label.setText(tr("settings.language"))
        self._hint.setText(tr("settings.hint"))
        self._close.setText(tr("common.close"))
        self._parent.retranslate()


class HubWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(app_icon())
        self._open: dict[str, QWidget] = {}

        self._title = QLabel(APP_NAME)
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet("font-size:24px;font-weight:bold;")
        self._subtitle = QLabel()
        self._subtitle.setAlignment(Qt.AlignCenter)
        self._subtitle.setStyleSheet("color:#888;")

        self._btn_record = self._big_button(lambda: self._launch("record"))
        self._btn_player = self._big_button(lambda: self._launch("player"))
        self._btn_sort = self._big_button(lambda: self._launch("sort"))
        self._btn_settings = QPushButton()
        self._btn_settings.clicked.connect(self._open_settings)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addSpacing(8)
        layout.addWidget(self._btn_record)
        layout.addWidget(self._btn_player)
        layout.addWidget(self._btn_sort)
        layout.addStretch(1)
        layout.addWidget(self._btn_settings)

        self.retranslate()
        self.resize(360, 340)

    def _big_button(self, slot) -> QPushButton:
        b = QPushButton()
        b.setMinimumHeight(56)
        b.setStyleSheet("font-size:15px;")
        b.clicked.connect(slot)
        return b

    def retranslate(self) -> None:
        self.setWindowTitle(APP_NAME)
        self._subtitle.setText(tr("hub.subtitle"))
        self._btn_record.setText(tr("hub.record"))
        self._btn_player.setText(tr("hub.player"))
        self._btn_sort.setText(tr("hub.sort"))
        self._btn_settings.setText(tr("hub.settings"))

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _launch(self, key: str) -> None:
        existing = self._open.get(key)
        if existing is not None:
            existing.showNormal()
            existing.raise_()
            existing.activateWindow()
            return
        if key == "record":
            win = recorder.launch_recording()
        elif key == "player":
            win = open_player()
        else:
            win = open_sorter()
        if win is None:           # dialog cancelled
            return
        self._open[key] = win
        win.destroyed.connect(lambda *_: self._open.pop(key, None))

    def closeEvent(self, event) -> None:  # noqa: N802
        rec = self._open.get("record")
        if rec is not None and getattr(rec, "_recording", False):
            if not ask_yes_no(self, APP_NAME, tr("hub.quit_while_recording")):
                event.ignore()
                return
        QApplication.instance().quit()
        event.accept()
