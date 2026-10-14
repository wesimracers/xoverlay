# base
from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect, QTimer
from PyQt6.QtGui import QPainter, QColor, QPen, QFont
import core
from last_lap_ranking import format_top_lap_entry


def parse_hex_color(val, default):  # 261001_CURSOR
    """Accept '#RRGGBB' or return default."""  # 261001_CURSOR
    try:  # 261001_CURSOR
        if isinstance(val, str):  # 261001_CURSOR
            s = val.strip()  # 261001_CURSOR
            if s.startswith("#") and len(s) == 7:  # 261001_CURSOR
                return QColor(int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        pass  # 261001_CURSOR
    return default  # 261001_CURSOR


class BaseWin(QWidget):
    def __init__(self, key: str):
        super().__init__()
        wcfg = (core.cfg.get("windows") or {}).get(key, {})
        x = int(wcfg.get("x", 100))
        y = int(wcfg.get("y", 100))
        w = int(wcfg.get("width", 300))
        h = int(wcfg.get("height", 200))
        self._key = key
        self._max_h = h
        self._max_w = w
        self.setGeometry(x, y, w, h)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self._drag = None

        # Per-widget fonts — built from cfg["windows"][key]["font_size"] when
        # set, falling back to the global core.FONT_NORMAL size. The user
        # asked for per-window font sizing (instead of one global GENERAL
        # value) so a small INFO bar can sit alongside a larger STANDINGS
        # table. apply_font() rebuilds these from current config, called
        # both at __init__ and any time the manager saves new settings.
        self.font_normal = None
        self.font_bold = None
        self.apply_font()

        # Visibility timer: allows hidden widgets to come back when state changes
        self._vis_timer = QTimer(self)
        self._vis_timer.setInterval(100)
        self._vis_timer.timeout.connect(self._apply_visibility)
        self._vis_timer.start()

        # Start hidden until first tick determines visibility (and until connected)
        self.setVisible(False)

    def apply_font(self):
        """(Re)build self.font_normal/bold from current config.

        Reads cfg["windows"][self._key]["font_size"] and falls back to the
        global core.FONT_NORMAL.pointSize() when not set. Family stays as
        the global family (no need to override per-widget). Called from
        __init__ and from manager.py after a config save so the widget
        live-refreshes without restart."""
        try:
            wcfg = (core.cfg.get("windows") or {}).get(self._key, {})
            global_size = int(core.FONT_NORMAL.pointSize() or 10)
            size = int(wcfg.get("font_size", 0) or 0) or global_size
            family = core.FONT_NORMAL.family() or "Consolas"
            self.font_normal = QFont(family, size)
            self.font_bold = QFont(family, size)
            self.font_bold.setBold(True)
        except Exception:
            # Last-resort fallback — always have a usable font on hand,
            # never let a config glitch leave the widget without one.
            self.font_normal = core.FONT_NORMAL
            self.font_bold = core.FONT_BOLD

    def mousePressEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            try:
                wins = core.cfg.setdefault("windows", {})
                wcfg = wins.setdefault(self._key, {})
                pos = self.pos()
                wcfg["x"] = pos.x()
                wcfg["y"] = pos.y()
                core.save_cfg()
            except Exception:
                pass
        self._drag = None

    def _auto_height(self, wanted_h: int):
        try:
            wanted = max(1, min(int(wanted_h), int(self._max_h)))
            if wanted != self.height():
                self.resize(self.width(), wanted)
        except Exception:
            pass

    def _apply_visibility(self):
        try:
            want = bool(self._should_be_visible())
        except Exception:
            want = False

        # setVisible() is safe to call repeatedly
        try:
            if self.isVisible() != want:
                self.setVisible(want)
        except Exception:
            pass

    def _should_be_visible(self):
        # Check enabled flag in config (manager ON/OFF toggle)
        try:
            wcfg = (core.cfg.get("windows") or {}).get(self._key, {})
            if not wcfg.get("enabled", True):
                return False
        except Exception:
            pass

        # Never show anything until connected
        try:
            if not getattr(core, "ir", None) or not core.ir.is_connected:
                return False
        except Exception:
            return False

        # ---- Driving / out-of-car detection ----
        # iRacing semantics:
        #   IsOnTrack       = True only when the player is IN THE COCKPIT
        #                     and the car is on track physics. Goes False
        #                     the instant the user pops the helmet (exits
        #                     car) — even if the car is still parked in
        #                     pits / garage / on track.
        #   IsOnTrackCar    = True whenever a car physics object exists in
        #                     the world. Stays True after the player exits
        #                     the car, during replays, etc. — too broad for
        #                     "show widgets while driving".
        #   IsReplayPlaying = True when watching a replay (user is not
        #                     actively driving the live session).
        #
        # User's rule: show widgets ONLY when in-cockpit driving; outside
        # the car (garage, exited, replay, menus) require the explicit
        # `show_in_garage` opt-in. Mapping cleanly:
        #     IsOnTrack && !IsReplayPlaying        → ALWAYS show
        #     anything else                        → defer to show_in_garage
        #
        # Earlier versions added an `IsOnTrackCar && !IsInGarage` fallback
        # which kept widgets visible after exiting the car at pit lane (car
        # still in world, NOT flagged as garage). That violated the user's
        # rule — widgets stayed up when the driver was clearly out of the
        # cockpit. Removed.
        try:
            if bool(core.sg("IsOnTrack", False)) and not bool(core.sg("IsReplayPlaying", False)):
                return True
        except Exception:
            pass

        # Not actively driving — defer to the show_in_garage opt-in
        try:
            wcfg = (core.cfg.get("windows") or {}).get(self._key, {})
            if wcfg.get("show_in_garage", False):
                return True
        except Exception:
            pass

        return False


class TableWin(BaseWin):
    def __init__(self, key, columns):
        super().__init__(key)
        self.columns = columns
        # Subclasses can disable the global top header row when they render
        # class-group headers (which already include per-group column headers).
        self._show_top_header = True

    def draw(self, p: QPainter, rows):
        # Only render columns whose "enabled" flag is True (or absent = True by default)
        active_cols = [c for c in self.columns if c.get("enabled", True)]

        # Each "_separator" row also gets a fresh COLUMN-HEADERS row painted
        # underneath it (per user spec — makes multi-class easier to read).
        # Need to add those repeat headers to the height budget so the
        # widget auto-resizes to fit.
        n_separators = sum(1 for r in rows if r.get("_separator"))
        n_top_laps = sum(1 for r in rows if r.get("_separator") and "_top_laps" in r)
        content_rows = len(rows) + n_separators + n_top_laps
        header_rows = 1 if self._show_top_header else 0
        wanted_h = (core.PAD_Y * 2) + (core.ROW_H * (header_rows + content_rows))
        self._auto_height(wanted_h)

        w = self.width()
        h = self.height()
        p.fillRect(self.rect(), QColor(0, 0, 0))

        x_positions = [core.PAD_X]
        x = core.PAD_X
        for col in active_cols:
            x += int(col.get("width", 40))
            x_positions.append(x)

        full_w = max(0, w - 2 * core.PAD_X)

        # Y-bands where vertical column dividers must NOT be drawn — the
        # full-width class separator and the repeated column-header row
        # below it. Without this, the yellow class line (and the header
        # row immediately under it) would have grey vertical lines slicing
        # through them, breaking the "continuous full-width" look the
        # user asked for.
        no_divider_bands = []   # list of (y_top, y_bot)

        def _draw_col_headers(y):
            p.setFont(self.font_bold)
            for i, col in enumerate(active_cols):
                x_h = x_positions[i]
                cw_h = int(col.get("width", 40))
                p.setPen(core.CLR_WHITE)
                p.drawText(
                    QRect(x_h, y, cw_h, core.ROW_H),
                    Qt.AlignmentFlag.AlignCenter,
                    str(col.get("label", "")).upper(),
                )
            p.setPen(QPen(QColor(90, 90, 90)))
            p.drawLine(core.PAD_X, y + core.ROW_H, w - core.PAD_X, y + core.ROW_H)

        # Optional top column-header row
        y0 = core.PAD_Y
        if self._show_top_header:
            _draw_col_headers(y0)

        # Iterate rows
        y = core.PAD_Y + (core.ROW_H if self._show_top_header else 0)
        non_sep_index = 0   # for alternating row colors (skip separator rows)

        for row in rows:
            if y + core.ROW_H > h - core.PAD_Y + 1:
                break

            if row.get("_separator"):
                # ---- Yellow full-width class header (NO column dividers) ----
                sep_top = y
                p.fillRect(QRect(core.PAD_X, y, full_w, core.ROW_H), QColor(255, 255, 0))
                p.setFont(self.font_bold)
                p.setPen(QColor(0, 0, 0))
                p.drawText(
                    QRect(core.PAD_X, y, full_w, core.ROW_H),
                    Qt.AlignmentFlag.AlignCenter,
                    str(row.get("label", "")).upper(),
                )
                y += core.ROW_H

                # Standings can place one compact fastest-last-laps strip
                # between each class title and its ordinary column headers.
                if "_top_laps" in row:
                    p.fillRect(QRect(core.PAD_X, y, full_w, core.ROW_H), QColor(255, 224, 178))
                    laps = row["_top_laps"]
                    if laps:
                        group_w = full_w / 3
                        labels = [format_top_lap_entry(lap) for lap in laps[:3]]
                        row_font = QFont(self.font_normal)
                        while row_font.pointSize() > 8:
                            p.setFont(row_font)
                            if max(p.fontMetrics().horizontalAdvance(label) for label in labels) <= group_w - 8:
                                break
                            row_font.setPointSize(row_font.pointSize() - 1)
                        p.setFont(row_font)
                        p.setPen(core.CLR_BLACK)
                        for j, label in enumerate(labels):
                            left = core.PAD_X + round(j * group_w)
                            right = core.PAD_X + round((j + 1) * group_w)
                            p.drawText(QRect(left, y, right - left, core.ROW_H),
                                       Qt.AlignmentFlag.AlignCenter, label)
                    p.setPen(QPen(QColor(155, 100, 40)))
                    for j in (1, 2):
                        xpos = core.PAD_X + round(j * full_w / 3)
                        p.drawLine(xpos, y, xpos, y + core.ROW_H)
                    y += core.ROW_H

                # Repeat column-headers under each class — easier to read in
                # multi-class. Width-positions are identical to the top
                # header so cells under it line up exactly.
                _draw_col_headers(y)
                hdr_bot = y + core.ROW_H
                y = hdr_bot

                # Block vertical dividers across BOTH the yellow line AND the
                # repeated column-header row, so the class header is one
                # continuous bar.
                no_divider_bands.append((sep_top, hdr_bot))
                # Reset the alternating-color counter for the new class group
                non_sep_index = 0
                continue

            # ---- Normal car row ----
            is_player = bool(row.get("is_player"))
            bg = (core.CLR_PLAYER_BG if is_player
                  else (core.CLR_ROW_A if (non_sep_index % 2 == 0) else core.CLR_ROW_B))
            p.fillRect(QRect(core.PAD_X, y, full_w, core.ROW_H), bg)

            p.setFont(self.font_bold if is_player else self.font_normal)

            for i, col in enumerate(active_cols):
                x = x_positions[i]
                cw = int(col.get("width", 40))
                cid = col.get("id")
                txt = str(row.get(cid, ""))

                if is_player:
                    try:
                        r, g, b, _ = bg.getRgb()
                        colr = core.CLR_BLACK if (0.2126*r + 0.7152*g + 0.0722*b) > 140 else core.CLR_WHITE
                    except Exception:
                        colr = core.CLR_BLACK
                else:
                    colr = row.get(f"{cid}_color", core.CLR_WHITE)

                p.setPen(colr)
                p.drawText(QRect(x, y, cw, core.ROW_H), Qt.AlignmentFlag.AlignCenter, txt)

                # underline = car is laps behind, overline = car is laps ahead
                if cid == "num" and not is_player:
                    ld = row.get("laps_diff", 0)
                    if ld != 0:
                        deco_pen = QPen(colr)
                        deco_pen.setWidth(1)
                        p.setPen(deco_pen)
                        if ld < 0:
                            p.drawLine(x + 2, y + core.ROW_H - 2, x + cw - 2, y + core.ROW_H - 2)
                        else:
                            p.drawLine(x + 2, y + 2, x + cw - 2, y + 2)

            # row underline
            p.setPen(QPen(QColor(45, 45, 45)))
            p.drawLine(core.PAD_X, y + core.ROW_H, w - core.PAD_X, y + core.ROW_H)
            y += core.ROW_H
            non_sep_index += 1

        # ---- Vertical column dividers (drawn last) ----
        # Drawn as SEGMENTS that skip every no-divider band, so class
        # separators and their repeated column-headers render as continuous
        # full-width lines without grey vertical breaks slicing through.
        p.setPen(QPen(core.CLR_GRID))
        full_top = core.PAD_Y
        full_bot = core.PAD_Y + core.ROW_H * (header_rows + content_rows)
        for xpos in x_positions[1:-1]:
            if xpos >= w:
                continue
            segments = [(full_top, full_bot)]
            for band_top, band_bot in no_divider_bands:
                new_segs = []
                for seg_top, seg_bot in segments:
                    if band_bot <= seg_top or band_top >= seg_bot:
                        new_segs.append((seg_top, seg_bot))
                        continue
                    if band_top > seg_top:
                        new_segs.append((seg_top, band_top))
                    if band_bot < seg_bot:
                        new_segs.append((band_bot, seg_bot))
                segments = new_segs
            for seg_top, seg_bot in segments:
                if seg_bot > seg_top:
                    p.drawLine(xpos, seg_top, xpos, seg_bot)


class RowBar(BaseWin):
    """Single-row widget that renders a horizontal sequence of cells with
    configurable per-cell widths and vertical separator lines between them
    — used by FUEL and INFO. Cells are produced by the subclass per tick
    via _build_cells(); each cell is (id, text, QColor). Disabled / unknown
    cells are skipped. Width per id comes from cfg[settings_key]["columns"].
    """

    def __init__(self, key: str, settings_key: str, default_columns: list):
        super().__init__(key)
        self._settings_key = settings_key
        s = core.cfg.get(settings_key) or {}
        self._default_columns = list(default_columns)
        # If no columns config exists yet, seed the defaults so the manager
        # column editor sees something on first launch.
        if "columns" not in s:
            s["columns"] = list(default_columns)
            core.cfg[settings_key] = s
            try:
                core.save_cfg()
            except Exception:
                pass
        self.columns = list(s.get("columns") or default_columns)

    def _column_lookup(self):
        return {c.get("id"): c for c in self.columns}

    def _draw_row(self, p: QPainter, cells: list):
        """Draw a single row of cells. Each cell tuple: (id, text, color).
        Cells are filtered/ordered by self.columns; widths come from there."""
        # Black bg consistent with other widgets
        p.fillRect(self.rect(), QColor(0, 0, 0))
        p.setFont(self.font_normal)

        cells_by_id = {cid: (txt, col) for (cid, txt, col) in cells}
        y0 = core.PAD_Y
        h = self.height() - 2 * core.PAD_Y
        x = core.PAD_X
        first = True
        for col_cfg in self.columns:
            if not col_cfg.get("enabled", True):
                continue
            cid = col_cfg.get("id")
            if cid not in cells_by_id:
                continue
            cw = int(col_cfg.get("width", 60))
            if not first:
                p.setPen(QPen(core.CLR_GRID))
                p.drawLine(x, y0, x, y0 + h)
                x += 1
            text, color = cells_by_id[cid]
            p.setPen(color or core.CLR_WHITE)
            p.drawText(QRect(x, y0, cw, h),
                       Qt.AlignmentFlag.AlignCenter, str(text))
            x += cw
            first = False


# if correct reply yes, else return solutions that are mandatory to work
