"""Responsive table rendering scoped exclusively to the Sectors widget."""

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QColor, QPen, QFontMetrics
from base import TableWin
import core


class CompactSectorTable(TableWin):
    _ranking_slots = 6
    _visible_row_count = 3 + _ranking_slots  # class, player, column labels, rankings
    _capacities = {"pos": "888", "num": "888", "sector": "8:88.888",
                   "sector_2": "8:88.888", "sector_3": "8:88.888", "tire": "W"}

    def __init__(self, key, columns):
        super().__init__(key, columns)
        self._uppercase_headers = False

    def _configured_width(self):
        window = (core.cfg.get("windows") or {}).get(self._key) or {}
        return max(1, int(window.get("width", self._max_w)))

    def _fit_content(self, width, height):
        """Keep the configured width and user anchor; only height follows row count."""
        width, height = self._configured_width(), max(1, int(height))
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)

    def _text_height(self):
        return max(QFontMetrics(self.font_normal).height(), QFontMetrics(self.font_bold).height()) + 2

    def _allocate_columns(self, interior_width):
        normal, bold = QFontMetrics(self.font_normal), QFontMetrics(self.font_bold)
        columns, weights = [], []
        for configured in self.columns:
            if not configured.get("enabled", True):
                continue
            col = dict(configured)
            template = self._capacities.get(col.get("id"), "")
            header = "Setor 888" if col.get("id", "").startswith("sector") else str(col.get("label", ""))
            weights.append(max(bold.horizontalAdvance(header), normal.horizontalAdvance(template),
                               bold.horizontalAdvance(template)) + 4)
            columns.append(col)
        if not columns:
            return []
        total = sum(weights)
        widths = [interior_width * weight // total for weight in weights]
        remainder_order = sorted(range(len(widths)),
                                 key=lambda i: (-(interior_width * weights[i] % total), i))
        for i in remainder_order[:interior_width - sum(widths)]:
            widths[i] += 1
        for col, width in zip(columns, widths):
            col["width"] = width
        return columns

    @staticmethod
    def _draw_cell_text(painter, rect, text):
        """Elide at the current font and clip each cell, even at tiny widths."""
        if rect.width() <= 4:
            return
        painter.save()
        painter.setClipRect(rect)
        fitted = painter.fontMetrics().elidedText(str(text), Qt.TextElideMode.ElideRight, rect.width() - 4)
        painter.drawText(rect.adjusted(2, 0, -2, 0), Qt.AlignmentFlag.AlignCenter, fitted)
        painter.restore()

    def _draw_data_row(self, painter, row, columns, y, row_h, interior, ordinal):
        is_player = bool(row.get("is_player"))
        bg = core.CLR_PLAYER_BG if is_player else (core.CLR_ROW_A if ordinal % 2 == 0 else core.CLR_ROW_B)
        painter.fillRect(QRect(core.PAD_X, y, interior, row_h), bg)
        painter.setFont(self.font_bold if is_player else self.font_normal)
        red, green, blue, _ = bg.getRgb()
        ink = core.CLR_BLACK if is_player and .2126 * red + .7152 * green + .0722 * blue > 140 else core.CLR_WHITE
        painter.setPen(ink)
        x = core.PAD_X
        for col in columns:
            self._draw_cell_text(painter, QRect(x, y, col["width"], row_h), row.get(col["id"], ""))
            x += col["width"]
        painter.setPen(QPen(QColor(45, 45, 45)))
        painter.drawLine(core.PAD_X, y + row_h, core.PAD_X + interior, y + row_h)

    def draw(self, painter, rows):
        row_h = self._text_height()
        self._draw_row_h = row_h
        self._fit_content(None, self._visible_row_count * row_h + 2 * core.PAD_Y)
        interior = max(0, self.width() - 2 * core.PAD_X)
        columns = self._allocate_columns(interior)
        self._draw_columns = columns
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        heading_rect = QRect(core.PAD_X, core.PAD_Y, interior, row_h)
        painter.fillRect(heading_rect, QColor(255, 255, 0))
        painter.setFont(self.font_bold)
        painter.setPen(core.CLR_BLACK)
        self._draw_cell_text(painter, heading_rect, rows[0].get("label", "").upper() if rows else "")
        y = core.PAD_Y + row_h
        self._draw_data_row(painter, rows[1] if len(rows) > 1 else {}, columns,
                            y, row_h, interior, 0)
        y += row_h
        x = core.PAD_X
        painter.setFont(self.font_bold)
        painter.setPen(core.CLR_WHITE)
        for col in columns:
            self._draw_cell_text(painter, QRect(x, y, col["width"], row_h), col.get("label", ""))
            x += col["width"]
        painter.setPen(QPen(QColor(90, 90, 90)))
        painter.drawLine(core.PAD_X, y + row_h, core.PAD_X + interior, y + row_h)
        data_y = y + row_h
        for ordinal, row in enumerate(rows[2:2 + self._ranking_slots]):
            y = data_y + ordinal * row_h
            self._draw_data_row(painter, row, columns, y, row_h, interior, ordinal)
        # Keep the boundary between dry and wet groups visible when both are used.
        if any(row.get("tire") == "W" for row in rows[2:]):
            painter.setPen(QPen(QColor(90, 90, 90)))
            painter.drawLine(core.PAD_X, data_y + 3 * row_h, core.PAD_X + interior, data_y + 3 * row_h)
        painter.setPen(QPen(core.CLR_GRID))
        x = core.PAD_X
        for col in columns[:-1]:
            x += col["width"]
            painter.drawLine(x, core.PAD_Y + row_h, x, core.PAD_Y + 2 * row_h)
            painter.drawLine(x, data_y, x, self.height() - core.PAD_Y)
