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


def ask_save_discard_cancel(parent, title: str, text: str) -> str:
    """Three-way question in the app language; returns "save", "discard" or "cancel".
    The default (Enter/Escape) button is "cancel" so an accidental key never saves
    or discards. Used when the recording window is closed via the window's X."""
    box = QMessageBox(QMessageBox.Question, title, text, QMessageBox.NoButton, parent)
    save = box.addButton(tr("record.close_save"), QMessageBox.AcceptRole)
    discard = box.addButton(tr("record.close_discard"), QMessageBox.DestructiveRole)
    cancel = box.addButton(tr("record.close_cancel"), QMessageBox.RejectRole)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box.exec()
    clicked = box.clickedButton()
    if clicked is save:
        return "save"
    if clicked is discard:
        return "discard"
    return "cancel"
