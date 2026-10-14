# hr
#
# Standalone heart-rate widget with a large heart shape and BPM text inside.
# Outside the heart is transparent so it can sit next to other widgets.

from PyQt6.QtGui import QPainter, QColor, QFont, QPainterPath, QPen
from PyQt6.QtCore import Qt, QRectF
import traceback

import core
from base import BaseWin, parse_hex_color as _parse_color  # 261001_CURSOR
import heart


# def _parse_color(val, default):
#     try:
#         if isinstance(val, str):
#             s = val.strip()
#             if s.startswith("#") and len(s) == 7:
#                 return QColor(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))
#     except Exception:
#         pass
#     return default


class HR(BaseWin):
    def __init__(self):
        super().__init__("hr")
        self._last_payload = {}
        self._heart_font_size = 24
        self._heart_text_color = QColor(255, 255, 255)
        self._heart_fill_color = QColor(0, 0, 0)
        self._heart_border_color = QColor(255, 255, 255)

        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        except Exception:
            pass

        self.apply_settings(core.cfg.get("heart_settings") or {})

    def apply_settings(self, s: dict):
        try:
            self._heart_font_size = max(8, int(s.get("heart_font_size", 24)))
        except Exception:
            self._heart_font_size = 24
        self._heart_text_color = _parse_color(s.get("heart_text_color", "#FFFFFF"), QColor(255, 255, 255))
        self._heart_fill_color = _parse_color(s.get("heart_fill_color", "#000000"), QColor(0, 0, 0))
        self._heart_border_color = _parse_color(s.get("heart_border_color", "#FFFFFF"), QColor(255, 255, 255))
        self.update()

    def update_data(self):
        # try:
        #     core.connect()
        # except Exception:
        #     pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    @staticmethod
    def _heart_path(r: QRectF):
        # Normalized heart curve mapped into rect r.
        l = r.left()
        t = r.top()
        w = r.width()
        h = r.height()

        def pt(xn, yn):
            return l + (xn * w), t + (yn * h)

        path = QPainterPath()
        x0, y0 = pt(0.50, 0.92)
        path.moveTo(x0, y0)

        c1x, c1y = pt(0.92, 0.64)
        c2x, c2y = pt(0.98, 0.36)
        ex, ey = pt(0.76, 0.22)
        path.cubicTo(c1x, c1y, c2x, c2y, ex, ey)

        c1x, c1y = pt(0.62, 0.10)
        c2x, c2y = pt(0.53, 0.17)
        ex, ey = pt(0.50, 0.27)
        path.cubicTo(c1x, c1y, c2x, c2y, ex, ey)

        c1x, c1y = pt(0.47, 0.17)
        c2x, c2y = pt(0.38, 0.10)
        ex, ey = pt(0.24, 0.22)
        path.cubicTo(c1x, c1y, c2x, c2y, ex, ey)

        c1x, c1y = pt(0.02, 0.36)
        c2x, c2y = pt(0.08, 0.64)
        ex, ey = pt(0.50, 0.92)
        path.cubicTo(c1x, c1y, c2x, c2y, ex, ey)

        path.closeSubpath()
        return path

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # Clear full widget to transparent first.
            from PyQt6.QtGui import QPainter as _QP
            p.setCompositionMode(_QP.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), QColor(0, 0, 0, 0))
            p.setCompositionMode(_QP.CompositionMode.CompositionMode_SourceOver)

            bpm = heart.latest_bpm()
            text = str(int(bpm)) if bpm is not None else "--"

            w = float(self.width())
            h = float(self.height())
            side = min(w, h) * 0.98
            heart_rect = QRectF(
                (w - side) / 2.0,
                (h - side) / 2.0,
                max(2.0, side),
                max(2.0, side),
            )

            heart_path = self._heart_path(heart_rect)
            border_w = max(1, int(round(side * 0.03)))
            p.setPen(QPen(self._heart_border_color, border_w))
            p.setBrush(self._heart_fill_color)
            p.drawPath(heart_path)

            # Centered number inside heart.
            font = QFont(self.font_bold)
            font.setBold(True)
            fit_pt = max(8, int(heart_rect.height() * 0.30))
            font.setPointSize(min(self._heart_font_size, fit_pt))
            p.setFont(font)
            p.setPen(self._heart_text_color)
            p.drawText(
                heart_rect,
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

            self._last_payload = {"bpm": bpm, "status": heart.status()}
            core.update_state_and_debug_dump(extra={"hr": self._last_payload})
        except Exception as ex:
            core._log(f"HR paint error: {ex!r}")
            core._log(traceback.format_exc())
