"""Thin RPM bar, with a continuous green/yellow/red color transition."""

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QColor, QPainter
import core
from base import BaseWin
from rpm_state import rpm_state, seed_rpm_config


class RPM(BaseWin):
    def __init__(self):
        seed_rpm_config(core.cfg)
        super().__init__("rpm")
        self.setWindowTitle("RPM")
        self._last_payload = rpm_state(None, {}, {})

    def update_data(self):
        if core.begin_frame():
            self._last_payload = rpm_state(
                core.sg("RPM", None), core.sg("DriverInfo", {}),
                core.cfg.get("rpm_settings") or {})
        else:
            self._last_payload = rpm_state(None, {}, {})
            self._last_payload["status"] = "disconnected"
        self.update()

    def apply_settings(self, settings):
        # Settings are read every tick, including after changing cars or setups.
        self.update_data()

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(10, 10, 10))
            fraction = self._last_payload["percent"] / 100.0
            if fraction > 0:
                color = QColor.fromHsvF((1.0 - fraction) / 3.0, 1.0, 1.0)
                painter.fillRect(QRectF(0, 0, self.width() * fraction, self.height()), color)
        finally:
            painter.end()
