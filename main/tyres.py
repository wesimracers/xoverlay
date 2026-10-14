# tyres
#
# 2x2 tyre temperature widget.  Layout per the user's spec — every text in its
# own cell, properly centred horizontally and vertically:
#
#     +-------------------+    +-------------------+
#     |        FL         |    |        FR         |     <- tyre label cell
#     +-----+------+------+    +------+------+-----+
#     | OUT |INNER |  IN  |    |  IN  |INNER | OUT |     <- zone label cells
#     +-----+------+------+    +------+------+-----+
#     |  72 |  77  |  82  |    |  78  |  76  |  72 |     <- temp value cells
#     +-----+------+------+    +------+------+-----+
#
#     +-------------------+    +-------------------+
#     |        RL         |    |        RR         |
#     +-----+------+------+    +------+------+-----+
#     | OUT |INNER |  IN  |    |  IN  |INNER | OUT |
#     +-----+------+------+    +------+------+-----+
#     |  74 |  78  |  81  |    |  77  |  75  |  73 |
#     +-----+------+------+    +------+------+-----+
#
# For LEFT  tyres, zone order is OUT | INNER | IN  (so IN faces the centre)
# For RIGHT tyres, zone order is IN  | INNER | OUT (so IN faces the centre)
#
# iRacing telemetry per tyre supplies CL / CM / CR (Center-Left / Middle /
# Center-Right of the contact patch).  Mapping:
#     LF/LR : CL = outer edge, CM = middle, CR = inner edge
#     RF/RR : CL = inner edge, CM = middle, CR = outer edge

from PyQt6.QtGui import QPainter, QColor, QPen, QFont
from PyQt6.QtCore import Qt, QRect
import traceback

import core
from base import BaseWin


_DEFAULT_RANGES = {
    "cold":     60.0,
    "warm":     75.0,
    "ideal_hi": 95.0,
    "hot":     105.0,
}


def _temp_color(t, ranges):
    try:
        v = float(t)
    except Exception:
        return QColor(80, 80, 80)
    if v < ranges["cold"]:
        return QColor(60, 130, 230)     # blue
    if v < ranges["warm"]:
        return QColor(60, 210, 220)     # cyan
    if v < ranges["ideal_hi"]:
        return QColor(40, 200, 80)      # green (ideal)
    if v < ranges["hot"]:
        return QColor(240, 210, 50)     # yellow
    return QColor(230, 60, 60)          # red


def _contrast(bg: QColor) -> QColor:
    try:
        lum = 0.2126 * bg.red() + 0.7152 * bg.green() + 0.0722 * bg.blue()
    except Exception:
        return QColor(0, 0, 0)
    return QColor(0, 0, 0) if lum > 140 else QColor(255, 255, 255)


def _clean_temp(v):
    try:
        f = float(v)
    except Exception:
        return None
    # Carcass temps are Celsius. Keep genuinely cold/hot conditions, but reject
    # zeroes and impossible values. Triplet coherence is checked separately.
    if 0.1 <= f <= 250.0:
        return f
    return None


def _clean_wear_values(values):
    raw = []
    for v in values:
        try:
            raw.append(float(v))
        except Exception:
            return []
    if len(raw) != 3:
        return []
    # The iRacing SDK documents wear as 0.0..1.0 remaining. Accepting arbitrary
    # 1..100 values hid stale-header corruption (engine/fuel values looked like
    # percentages), so a complete coherent triplet is required.
    if not all(0.0 <= v <= 1.0 for v in raw):
        return []
    if max(raw) <= 0.0 or (min(raw) <= 0.0 < max(raw)):
        return []
    return [v * 100.0 for v in raw]


def _draw_cell(p: QPainter, rect: QRect, text: str,
               bg: QColor, fg: QColor, border: bool, font: QFont):
    """Draw a single cell: filled background + centred text + optional border."""
    p.fillRect(rect, bg)
    if border:
        p.setPen(QPen(QColor(70, 70, 70), 1))
        p.drawRect(rect)
    p.setFont(font)
    p.setPen(fg)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
               str(text))


class Tyres(BaseWin):
    def __init__(self):
        super().__init__("tyres")
        s = core.cfg.get("tyre_settings") or {}
        self.ranges = {
            "cold":     float(s.get("cold_temp",  _DEFAULT_RANGES["cold"])),
            "warm":     float(s.get("warm_temp",  _DEFAULT_RANGES["warm"])),
            "ideal_hi": float(s.get("ideal_high", _DEFAULT_RANGES["ideal_hi"])),
            "hot":      float(s.get("hot_temp",   _DEFAULT_RANGES["hot"])),
        }
        self._last_payload = {}
        self._last_reset_epoch = core._RESET_EPOCH[0]
        self._temp_signature = None
        self._temp_last_change_t = None
        self._temp_updates_seen = 0

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    def _read_tyre(self, prefix):
        """Return sanitized (CL, CM, CR) Celsius values."""
        try:
            vals = (
                _clean_temp(core.sg(f"{prefix}tempCL", None)),
                _clean_temp(core.sg(f"{prefix}tempCM", None)),
                _clean_temp(core.sg(f"{prefix}tempCR", None)),
            )
            if any(v is None for v in vals):
                return None
            # A real carcass triplet is spatially close. A giant edge spread is
            # another strong stale-offset signature and should never be drawn.
            if max(vals) - min(vals) > 65.0:
                return None
            return vals
        except Exception:
            return None

    def _temperature_diagnostics(self, tyres):
        epoch = core._RESET_EPOCH[0]
        if epoch != self._last_reset_epoch:
            self._last_reset_epoch = epoch
            self._temp_signature = None
            self._temp_last_change_t = None
            self._temp_updates_seen = 0

        flattened = []
        for tyre in tyres:
            if tyre:
                flattened.extend(tyre)
        now = core.session_time()
        if len(flattened) == 12:
            signature = tuple(round(float(value), 3) for value in flattened)
            if signature != self._temp_signature:
                self._temp_signature = signature
                self._temp_last_change_t = now
                self._temp_updates_seen += 1

        age = None
        if self._temp_last_change_t is not None and now >= self._temp_last_change_t:
            age = round(now - self._temp_last_change_t, 1)
        layout = core.telemetry_layout_status()
        return {
            "valid_zones": len(flattened),
            "sdk_updates_seen": self._temp_updates_seen,
            "seconds_since_sdk_change": age,
            "layout_generation": layout.get("generation"),
            "mapping_ok": layout.get("mapping_ok"),
        }

    def _read_wear_pct(self, prefix):
        """Return the WORST (lowest) remaining-tread percentage across the
        three zones of one tyre, clamped to [0, 99] so it's always 2 digits.

        iRacing exposes per-zone wear floats {prefix}wearL/M/R in the range
        0.0 (bald) .. 1.0 (full tread). 'Worst' = most worn = the smallest
        of the three. Returns None when telemetry is unavailable (e.g., on
        first connect before the buffer fills).

        Verified against data_20260427_191002.json — vars present and 0-1
        bounded throughout the race."""
        try:
            vals = _clean_wear_values((
                core.sg(f"{prefix}wearL", None),
                core.sg(f"{prefix}wearM", None),
                core.sg(f"{prefix}wearR", None),
            ))
            if not vals:
                return None
            pct = int(round(min(vals)))
            # Clamp so display stays 2 digits — show "99" for fully fresh
            # tyres rather than overflowing the layout with "100".
            return max(0, min(99, pct))
        except Exception:
            return None

    # -- one tyre quadrant: 3-column × 3-row mini-grid ----------------------

    def _draw_tyre_block(self, p: QPainter, area: QRect, label: str,
                         tyre, side_left: bool, wear_pct=None):
        """Render one 3x3 cell tyre block inside `area`. Three rows:
            row 0 — tyre label spanning all 3 columns (incl. worst-wear pct)
            row 1 — zone labels (3 cells)
            row 2 — temp values with colored backgrounds (3 cells)
        wear_pct: int in [0, 99] of the WORST remaining tread % across the
        three zones, or None if not available."""
        gap = 2
        # Row heights — label row sized like a header, two data rows equal
        header_h = max(int(area.height() * 0.30), core.ROW_H + 2)
        zone_h   = max(int(area.height() * 0.25), 14)
        value_h  = area.height() - header_h - zone_h - 3 * gap
        if value_h < 12:
            value_h = max(12, area.height() - header_h - zone_h)

        # Three equal columns inside the block (with small gaps)
        col_w = (area.width() - 4 * gap) // 3
        x0 = area.x() + gap
        y0 = area.y() + gap
        y_zones = y0 + header_h + gap
        y_vals  = y_zones + zone_h + gap

        # ---- Row 0: tyre label + worst-wear pct (spans all 3 columns) ----
        # Format: "FL 97" — always 2-digit (clamped to 99).
        label_rect = QRect(x0, y0, col_w * 3 + 2 * gap, header_h)
        # Per-widget font: respects cfg["windows"]["tyres"]["font_size"] if set.
        label_font = QFont(self.font_bold)
        label_font.setPointSize(max(self.font_bold.pointSize() + 4,
                                    int(header_h * 0.7)))
        label_font.setBold(True)
        if wear_pct is not None:
            label_text = f"{label} {wear_pct:02d}"
        else:
            label_text = label
        _draw_cell(p, label_rect, label_text,
                   bg=QColor(20, 20, 20),
                   fg=QColor(255, 255, 255),
                   border=True, font=label_font)

        # ---- Row 1: zone labels ----
        # Layout matches "looking down at the car from above": OUT is on the
        # outside-of-car side, IN is toward the car centreline.
        if side_left:
            zone_labels = ("OUT", "INNER", "IN")
        else:
            zone_labels = ("IN", "INNER", "OUT")

        zone_font = QFont(self.font_bold)
        zone_font.setPointSize(max(8, int(zone_h * 0.55)))
        zone_font.setBold(True)
        for i, zlbl in enumerate(zone_labels):
            cx = x0 + i * (col_w + gap)
            r = QRect(cx, y_zones, col_w, zone_h)
            _draw_cell(p, r, zlbl,
                       bg=QColor(35, 35, 35),
                       fg=QColor(200, 200, 200),
                       border=True, font=zone_font)

        # ---- Row 2: temp values with colored backgrounds ----
        # iRacing CL / CM / CR convention (corrected per user observation):
        #     LEFT-side tyres  : CL = OUTER edge of tyre, CR = INNER edge
        #     RIGHT-side tyres : CL = INNER edge,         CR = OUTER edge
        # Earlier the mapping was reversed — the OUT label was reading the
        # inner-edge sensor and vice-versa. The user spotted it on track
        # ("OUT values should be on IN and IN on OUT"); this swap fixes it.
        if tyre is None:
            cl = cm = cr = None
        else:
            cl, cm, cr = tyre
        if side_left:
            outer_t, middle_t, inner_t = cl, cm, cr      # LF/LR: CL=outer, CR=inner
        else:
            inner_t, middle_t, outer_t = cl, cm, cr      # RF/RR: CL=inner, CR=outer

        if side_left:
            zone_temps = (outer_t, middle_t, inner_t)   # display L→R: OUT / INNER / IN
        else:
            zone_temps = (inner_t, middle_t, outer_t)   # display L→R: IN / INNER / OUT

        val_font = QFont(self.font_bold)
        val_font.setPointSize(max(11, int(value_h * 0.55)))
        val_font.setBold(True)

        for i, t in enumerate(zone_temps):
            cx = x0 + i * (col_w + gap)
            r = QRect(cx, y_vals, col_w, value_h)
            if t is None:
                _draw_cell(p, r, "—",
                           bg=QColor(25, 25, 25),
                           fg=QColor(120, 120, 120),
                           border=True, font=val_font)
            else:
                bg = _temp_color(t, self.ranges)
                fg = _contrast(bg)
                try:
                    txt = f"{int(round(float(t)))}"
                except Exception:
                    txt = "?"
                _draw_cell(p, r, txt, bg=bg, fg=fg, border=True, font=val_font)

    # -- paint --------------------------------------------------------------

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            p.fillRect(self.rect(), QColor(0, 0, 0))

            if not core.ir.is_connected:
                p.setFont(self.font_normal)
                p.setPen(core.CLR_WHITE)
                p.drawText(QRect(core.PAD_X, core.PAD_Y,
                                 self.width() - 2 * core.PAD_X,
                                 self.height() - 2 * core.PAD_Y),
                           Qt.AlignmentFlag.AlignCenter, "TYRES: DISCONNECTED")
                return

            # Session transition guard: only during reset-grace, then resume
            # normal tyre rendering. This avoids getting stuck on placeholder.
            if core.is_in_reset_grace():
                p.setFont(self.font_bold)
                p.setPen(QColor(255, 200, 0))
                p.drawText(QRect(core.PAD_X, core.PAD_Y,
                                 self.width() - 2 * core.PAD_X,
                                 self.height() - 2 * core.PAD_Y),
                           Qt.AlignmentFlag.AlignCenter, "TYRES: NEW SESSION…")
                self._last_payload = {"inactive": True, "reason": "reset_grace"}
                core.update_state_and_debug_dump(extra={"tyres": self._last_payload})
                return

            lf = self._read_tyre("LF")
            rf = self._read_tyre("RF")
            lr = self._read_tyre("LR")
            rr = self._read_tyre("RR")

            # Worst-zone remaining-tread % per tyre, clamped 0..99 for the label.
            lf_w = self._read_wear_pct("LF")
            rf_w = self._read_wear_pct("RF")
            lr_w = self._read_wear_pct("LR")
            rr_w = self._read_wear_pct("RR")

            # ---- Compute the 2×2 layout area, centred in the widget ------
            outer_pad = core.PAD_X
            mid_gap   = max(8, core.PAD_X * 2)   # gap between left and right tyres
            row_gap   = max(8, core.PAD_Y * 2)   # gap between front and rear

            usable_w = self.width()  - 2 * outer_pad - mid_gap
            usable_h = self.height() - 2 * outer_pad - row_gap
            block_w  = max(80, usable_w // 2)
            block_h  = max(60, usable_h // 2)

            # Centre the whole 2×2 grid inside the window
            grid_w = block_w * 2 + mid_gap
            grid_h = block_h * 2 + row_gap
            origin_x = (self.width()  - grid_w) // 2
            origin_y = (self.height() - grid_h) // 2

            # FL (top-left)
            self._draw_tyre_block(p,
                QRect(origin_x, origin_y, block_w, block_h),
                "FL", lf, side_left=True, wear_pct=lf_w)
            # FR (top-right)
            self._draw_tyre_block(p,
                QRect(origin_x + block_w + mid_gap, origin_y, block_w, block_h),
                "FR", rf, side_left=False, wear_pct=rf_w)
            # RL (bottom-left)
            self._draw_tyre_block(p,
                QRect(origin_x, origin_y + block_h + row_gap, block_w, block_h),
                "RL", lr, side_left=True, wear_pct=lr_w)
            # RR (bottom-right)
            self._draw_tyre_block(p,
                QRect(origin_x + block_w + mid_gap, origin_y + block_h + row_gap,
                      block_w, block_h),
                "RR", rr, side_left=False, wear_pct=rr_w)

            # ---- Capture payload ----
            def _trip(t):
                if not t:
                    return None
                try:
                    vals = [
                        (round(float(v), 1) if v is not None else None)
                        for v in (t[0], t[1], t[2])
                    ]
                    return vals if any(v is not None for v in vals) else None
                except Exception:
                    return None
            self._last_payload = {
                "LF": _trip(lf), "RF": _trip(rf),
                "LR": _trip(lr), "RR": _trip(rr),
                "wear": {"LF": lf_w, "RF": rf_w, "LR": lr_w, "RR": rr_w},
                "telemetry": self._temperature_diagnostics((lf, rf, lr, rr)),
                "edge_order": {
                    "left_side": ["OUT", "MIDDLE", "IN"],
                    "right_side": ["IN", "MIDDLE", "OUT"],
                },
                "ranges": dict(self.ranges),
            }
            core.update_state_and_debug_dump(extra={"tyres": self._last_payload})

        except Exception as ex:
            core._log(f"Tyres paint error: {ex!r}")
            core._log(traceback.format_exc())
