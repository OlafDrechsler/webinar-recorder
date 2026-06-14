"""Pre-recording dialog: choose where recordings are stored.

Shown once at startup, before any audio is recorded (see app.py). It is
pre-filled with the folder chosen last time (persisted via core.settings), so on
most launches the user just confirms with "Aufnahme starten". The picked path is
saved immediately, so it survives restarts — and stays correct even if the
program itself is later reinstalled to a different location.

Typical use: point this at a OneDrive-synced folder so recordings made on one
machine appear on the others.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.settings import get_data_dir, set_data_dir


class StorageDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Speicherort wählen")
        self._chosen: Path | None = None

        info = QLabel(
            "Wo sollen die Aufnahmen gespeichert werden?\n"
            "Tipp: einen OneDrive-Ordner wählen, der zwischen den Rechnern "
            "synchronisiert wird. Die Auswahl wird gemerkt und beim nächsten "
            "Start vorausgefüllt."
        )
        info.setWordWrap(True)

        # Pre-fill with the remembered (or default) folder.
        self._edit = QLineEdit(str(get_data_dir()))
        browse = QPushButton("Durchsuchen…")
        browse.clicked.connect(self._browse)
        path_row = QHBoxLayout()
        path_row.addWidget(self._edit, stretch=1)
        path_row.addWidget(browse)

        cancel = QPushButton("Abbrechen")
        cancel.clicked.connect(self.reject)
        ok = QPushButton("Weiter")
        ok.setDefault(True)
        ok.clicked.connect(self._accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel)
        btn_row.addWidget(ok)

        layout = QVBoxLayout(self)
        layout.addWidget(info)
        layout.addLayout(path_row)
        layout.addLayout(btn_row)
        self.resize(540, 170)

    def _browse(self) -> None:
        start = self._edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Ordner wählen", start)
        if folder:
            self._edit.setText(folder)

    def _accept(self) -> None:
        text = self._edit.text().strip()
        if not text:
            return  # nothing entered; keep the dialog open
        self._chosen = Path(text)
        set_data_dir(self._chosen)  # persist now, so it is remembered next time
        self.accept()

    def chosen_path(self) -> Path | None:
        """The folder the user confirmed, or None if cancelled."""
        return self._chosen
