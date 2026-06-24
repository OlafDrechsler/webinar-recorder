"""Live microphone level meter for setting the voice-activation threshold.

Shows the current input level as a bar with a draggable threshold marker. While
open, speaking should push the bar past the threshold (turning the indicator
green) and silence should fall below it — that's how the user calibrates the
auto-segmentation sensitivity.

It also offers a device picker: if the meter mirrors the speaker output, the
wrong device (e.g. "Stereomix") is selected — switch to the real mic here. The
choice is remembered for next time via core.settings.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.settings import set_mic_device

# Slider integer range maps to a normalised threshold of 0..0.20.
_SLIDER_MAX = 200
_THRESH_PER_STEP = 0.001
# Level (0..~0.3 typically) scaled onto the 0..100 progress bar.
_LEVEL_SCALE = 300


class MicLevelWindow(QWidget):
    def __init__(self, mic_recorder) -> None:
        super().__init__()
        self.setWindowTitle(tr("mic.level_test"))
        self._mic = mic_recorder

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setTextVisible(False)

        # Device picker — switch away from Stereomix/loopback to the real mic.
        self._device_box = QComboBox()
        self._populate_devices()
        self._device_box.currentTextChanged.connect(self._on_device)

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(0, _SLIDER_MAX)
        self._slider.setValue(int(mic_recorder.threshold / _THRESH_PER_STEP))
        self._slider.valueChanged.connect(self._on_threshold)

        self._info = QLabel()
        self._state = QLabel()

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("mic.test_instruction")))
        dev_row = QHBoxLayout()
        dev_row.addWidget(QLabel(tr("mic.device_label")))
        dev_row.addWidget(self._device_box, stretch=1)
        layout.addLayout(dev_row)
        layout.addWidget(self._bar)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("mic.threshold_label")))
        row.addWidget(self._slider)
        layout.addLayout(row)
        layout.addWidget(self._info)
        layout.addWidget(self._state)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(50)
        self._on_threshold(self._slider.value())

    def _populate_devices(self) -> None:
        """Fill the picker with real input devices and select the active one."""
        self._device_box.blockSignals(True)
        self._device_box.clear()
        names = self._mic.available_devices()
        self._device_box.addItems(names)
        current = self._mic.device_name
        if current and current in names:
            self._device_box.setCurrentText(current)
        self._device_box.blockSignals(False)

    def _on_device(self, name: str) -> None:
        if not name or name == self._mic.device_name:
            return
        self._mic.set_device(name)  # restart capture on the chosen device
        set_mic_device(name)        # remember for next launch

    def _on_threshold(self, value: int) -> None:
        thr = value * _THRESH_PER_STEP
        self._mic.set_threshold(thr)
        self._info.setText(tr("mic.threshold_value", value=thr))

    def _refresh(self) -> None:
        level = self._mic.level
        self._bar.setValue(min(100, int(level * _LEVEL_SCALE)))
        over = level > self._mic.threshold
        self._state.setText(tr("mic.over") if over else tr("mic.under"))
        self._state.setStyleSheet("color: green;" if over else "color: gray;")

    def closeEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
