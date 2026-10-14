# wind
#
# Circular wind-direction widget. Renders a compass with an arrow that
# points to where the WIND is going RELATIVE TO THE CAR — so when the car
# turns, the arrow rotates accordingly. The numeric wind speed in km/h is
# shown inside the dial.
#
# Why "relative to the car" matters
# ---------------------------------
# A static wind direction (e.g. "wind from NNE") isn't useful when you're
# wrestling a car at 200 km/h on a banked oval — what you actually need is
# "wind is coming over my LEFT shoulder right now". This widget computes
# that on the fly:
#
#     relative_heading = wind_dir - yaw_to_north
#
# The relative_heading is then drawn as an arrow pointing in the direction
# the wind is GOING (i.e., where it'll push the car), with 0 rad = forward
# (arrow points up = wind helping you), π rad = backward (wind in your face),
# π/2 = wind pushing you LEFT (i.e., wind coming from your RIGHT), etc.
#
# iRacing telemetry conventions
# ------------------------------
#  - WindDir   : radians, where the wind is COMING FROM. 0 = from north,
#                π/2 = from east, π = from south, 3π/2 = from west.
#                (Standard meteorological convention.)
#  - WindVel   : metres per second
#  - YawNorth  : radians, car heading. 0 = facing north, π/2 = facing east,
#                same orientation as WindDir.
#
# To convert "wind coming FROM" → "wind going TO" we add π. Subtracting
# YawNorth converts world-frame → car-frame:
#
#     wind_going_to_world = WindDir + π
#     wind_going_to_car   = (WindDir + π) - YawNorth
#
# So an arrow at angle = (WindDir + π - YawNorth) inside the widget points
# in the direction the wind is actually pushing the car relative to its
# current heading. We rotate the arrow so 0 = up (forward), clockwise +.

import math
import traceback
from PyQt6.QtCore import Qt, QPointF, QTimer, QRectF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QFont, QPolygonF, QFontMetricsF

import core
from base import BaseWin, parse_hex_color as _parse_color  # 261001_CURSOR


# def _parse_color(val, default):
#     try:
#         if isinstance(val, str):
#             s = val.strip()
#             if s.startswith("#") and len(s) == 7:
#                 r = int(s[1:3], 16)
#                 g = int(s[3:5], 16)
#                 b = int(s[5:7], 16)
#                 return QColor(r, g, b)
#     except Exception:
#         pass
#     return default


def _clamp(v, lo, hi):
    try:
        f = float(v)
    except Exception:
        return lo
    return max(lo, min(hi, f))


class Wind(BaseWin):
    """Circular dial showing car-relative wind direction and speed."""

    def __init__(self):
        super().__init__("wind")
        s = core.cfg.get("wind_settings") or {}
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._show_kmh = bool(s.get("show_kmh", True))
        self._arrow_color = _parse_color(s.get("arrow_color", "#FFC800"),
                                         QColor(255, 200, 0))
        self._circle_color = _parse_color(s.get("circle_color", "#101010"),
                                          QColor(16, 16, 16))
        self._border_color = _parse_color(s.get("border_color", "#FFFFFF"),
                                          QColor(255, 255, 255))
        self._arrow_scale = _clamp(s.get("arrow_size", 1.0), 0.4, 1.6)
        self._speed_box_color = _parse_color(s.get("speed_box_color", "#000000"),
                                             QColor(0, 0, 0))
        self._speed_text_color = _parse_color(s.get("speed_text_color", "#FFFFFF"),
                                              QColor(255, 255, 255))
        self._speed_box_w = _clamp(s.get("speed_box_width", 1.0), 0.6, 2.5)
        self._speed_box_h = _clamp(s.get("speed_box_height", 1.0), 0.6, 2.5)

        # self._timer = QTimer(self)
        # self._timer.timeout.connect(self.update_data)
        # self._timer.start(int(s.get("update_ms", 250)))
        self._timer = None  # 261001_CURSOR

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    def apply_settings(self, s: dict):
        try:
            self._show_kmh = bool(s.get("show_kmh", True))
            self._arrow_color = _parse_color(s.get("arrow_color", "#FFC800"),
                                             self._arrow_color)
            self._circle_color = _parse_color(s.get("circle_color", "#101010"),
                                              self._circle_color)
            self._border_color = _parse_color(s.get("border_color", "#FFFFFF"),
                                              self._border_color)
            self._arrow_scale = _clamp(s.get("arrow_size", 1.0), 0.4, 1.6)
            self._speed_box_color = _parse_color(s.get("speed_box_color", "#000000"),
                                                 self._speed_box_color)
            self._speed_text_color = _parse_color(s.get("speed_text_color", "#FFFFFF"),
                                                  self._speed_text_color)
            self._speed_box_w = _clamp(s.get("speed_box_width", 1.0), 0.6, 2.5)
            self._speed_box_h = _clamp(s.get("speed_box_height", 1.0), 0.6, 2.5)
            if self._timer:
                self._timer.setInterval(int(s.get("update_ms", 250)))
            self.update()
        except Exception:
            pass

    # ------------------------------------------------------------------

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

            # ---- Read telemetry ----
            try:
                wind_dir = float(core.sg("WindDir", 0.0) or 0.0)     # rad, from
                wind_vel = float(core.sg("WindVel", 0.0) or 0.0)     # m/s
                yaw_north = float(core.sg("YawNorth", 0.0) or 0.0)   # rad
            except Exception:
                wind_dir = 0.0
                wind_vel = 0.0
                yaw_north = 0.0

            # Convert "wind from" → "wind to", then world → car-relative.
            # Result is in radians where 0 = forward, +CW. Wrap into [0, 2π).
            rel = (wind_dir + math.pi - yaw_north) % (2.0 * math.pi)

            # m/s → km/h for display (user explicitly asked for km/h).
            kmh = wind_vel * 3.6

            # ---- Geometry ----
            w = self.width()
            h = self.height()
            cx = w / 2.0
            pad = 4.0
            base_font_pt = float(self.font_bold.pointSizeF() or self.font_bold.pointSize() or 10.0)

            speed_txt = f"{kmh:.0f}km/h"
            speed_font = QFont(self.font_bold)
            speed_font.setBold(True)
            speed_pt = int(max(8.0, min(float(min(w, h)) * 0.22, base_font_pt * 2.2)))
            speed_font.setPointSize(speed_pt)
            speed_fm = QFontMetricsF(speed_font)
            speed_h = speed_fm.height() if self._show_kmh else 0.0
            speed_gap = 2.0 if self._show_kmh else 0.0
            base_speed_box_h = max(10.0, speed_h + 4.0)
            speed_box_h = (base_speed_box_h * self._speed_box_h) if self._show_kmh else 0.0

            max_rx = max(8.0, (w / 2.0) - pad)
            max_ry = max(8.0, ((h - speed_box_h - speed_gap - (2.0 * pad)) / 2.0))
            radius = max(8.0, min(max_rx, max_ry))
            cy = pad + radius

            # ---- Compass ring ----
            # Thin grey circle so the dial reads as a circle even on a black
            # background. Plus 4 tick marks at the cardinal positions to
            # ground the eye.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(self._circle_color))
            p.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

            ring_pen = QPen(self._border_color)
            ring_pen.setWidth(2)
            p.setPen(ring_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - radius, cy - radius,
                                 radius * 2, radius * 2))

            # Cardinal ticks — short marks at 0/90/180/270 inside the ring.
            tick_pen = QPen(self._border_color)
            tick_pen.setWidth(2)
            p.setPen(tick_pen)
            for ang_deg in (0, 90, 180, 270):
                a = math.radians(ang_deg)
                # In our convention 0 = forward (up on screen). Screen Y is
                # inverted (down is positive), so a point at angle a (with
                # 0=up, +=CW) maps to (cx + r·sin(a), cy - r·cos(a)).
                x_out = cx + radius * math.sin(a)
                y_out = cy - radius * math.cos(a)
                x_in  = cx + (radius - 6) * math.sin(a)
                y_in  = cy - (radius - 6) * math.cos(a)
                p.drawLine(QPointF(x_in, y_in), QPointF(x_out, y_out))

            # Small "F" label at the top so the user can tell instantly which
            # way is "forward" without having to interpret the arrow alone.
            try:
                lbl_font = QFont(self.font_bold)
                lbl_pt = int(max(8.0, min(radius * 0.22, base_font_pt * 1.4)))
                lbl_font.setPointSize(lbl_pt)
                lbl_font.setBold(True)
                p.setFont(lbl_font)
                p.setPen(self._border_color)
                fr = QRectF(cx - 10, cy - radius - 2, 20, 12)
                # Move the F just inside the ring at the top
                fr = QRectF(cx - 8, cy - radius + 1, 16, max(10, int(radius * 0.25)))
                p.drawText(fr, Qt.AlignmentFlag.AlignCenter, "F")
            except Exception:
                pass

            # ---- Arrow ----
            # Triangle pointing at `rel`. Built in local coords (apex up),
            # then rotated by `rel` about the centre using a QTransform-free
            # manual rotation so we don't disturb the painter state.
            arrow_len = min(radius * 0.92, radius * 0.78 * self._arrow_scale)
            arrow_half = max(3.0, min(radius * 0.34, radius * 0.22 * self._arrow_scale))
            # Local pts: apex at (0, -arrow_len), base at (±arrow_half, +arrow_half)
            local = [
                (0.0,          -arrow_len),
                ( arrow_half,   arrow_half),
                (0.0,           arrow_half * 0.35),
                (-arrow_half,   arrow_half),
            ]
            cosA = math.cos(rel)
            sinA = math.sin(rel)
            poly = QPolygonF()
            for lx, ly in local:
                # Rotate: x' = lx·cos - ly·sin ; y' = lx·sin + ly·cos
                rx = lx * cosA - ly * sinA
                ry = lx * sinA + ly * cosA
                poly.append(QPointF(cx + rx, cy + ry))

            p.setBrush(QBrush(self._arrow_color))
            p.setPen(QPen(self._arrow_color))
            p.drawPolygon(poly)

            # ---- Speed text (km/h) — outside, below the circle ----
            if self._show_kmh:
                p.setFont(speed_font)
                base_speed_box_w = max(24.0, speed_fm.horizontalAdvance(speed_txt) + 10.0)
                speed_box_w = _clamp(base_speed_box_w * self._speed_box_w, 24.0, max(24.0, w - (2.0 * pad)))
                box_x = cx - (speed_box_w / 2.0)
                box_y = cy + radius + speed_gap
                box_r = QRectF(box_x, box_y, speed_box_w, max(10.0, speed_box_h))

                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(self._speed_box_color))
                p.drawRect(box_r)

                p.setPen(self._speed_text_color)
                tr = QRectF(box_x, box_y, speed_box_w, max(10.0, speed_box_h))
                p.drawText(tr,
                           Qt.AlignmentFlag.AlignCenter
                           | Qt.AlignmentFlag.AlignVCenter,
                           speed_txt)

            # ---- Debug payload ----
            try:
                core.update_state_and_debug_dump(extra={
                    "wind": {
                        "wind_dir_rad":  wind_dir,
                        "wind_vel_ms":   wind_vel,
                        "yaw_north_rad": yaw_north,
                        "relative_rad":  rel,
                        "kmh":           kmh,
                    }
                })
            except Exception:
                pass

        except Exception as ex:
            core._log(f"Wind paint error: {ex!r}")
            core._log(traceback.format_exc())


# if correct reply yes, else return solutions that are mandatory to work
