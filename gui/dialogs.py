"""Small shared dialog helpers.

Qt's standard-button texts ("Yes"/"No") are only localized when Qt's own
translation files are loaded, which this app doesn't do — so confirmation boxes
showed English buttons regardless of the chosen language. ``ask_yes_no`` builds
the buttons from our own i18n instead, with "No" as the safe default.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from core.i18n import tr


def ask_yes_no(parent, title: str, text: str) -> bool:
    """Modal Ja/Nein question in the app language; returns True only on "Ja".
    The default (focused) button is "Nein" so Enter never confirms by accident."""
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    yes = box.addButton(tr("common.yes"), QMessageBox.YesRole)
    no = box.addButton(tr("common.no"), QMessageBox.NoRole)
    box.setDefaultButton(no)
    box.exec()
    return box.clickedButton() is yes
