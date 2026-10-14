import copy
from pathlib import Path
import unittest
from unittest.mock import patch

from headless_widgets import core, render, basic_data, set_data
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QFontMetrics, QImage, QFontDatabase
from base import TableWin, RowBar


class Rows(TableWin):
    def __init__(self, columns, rows):
        super().__init__("compact_test", columns)
        self.rows = rows
        self._show_top_header = False

    def paintEvent(self, event):
        painter = QPainter(self)
        self.draw(painter, self.rows)
        painter.end()


class Bar(RowBar):
    def __init__(self, columns, cells):
        super().__init__("compact_test", "compact_test_settings", columns)
        self.cells = cells

    def paintEvent(self, event):
        painter = QPainter(self)
        self._draw_row(painter, self.cells)
        painter.end()


class CompactLayoutTests(unittest.TestCase):
    def setUp(self):
        # Real font metrics also work with Windows' offscreen Qt platform.
        for name in ("consola.ttf", "consolab.ttf", "segoeui.ttf", "segoeuib.ttf"):
            path = Path("C:/Windows/Fonts") / name
            if path.exists():
                QFontDatabase.addApplicationFont(str(path))
        self.cfg = copy.deepcopy(core.cfg)
        core.cfg["windows"]["compact_test"] = dict(x=123, y=45, width=900, height=20, font_size=12)
        set_data(*basic_data())

    def tearDown(self):
        core.cfg = self.cfg

    def test_existing_table_retains_configured_width_columns_and_row_height(self):
        core.cfg["windows"]["compact_test"]["height"] = 600
        columns = [{"id": "num", "label": "#", "width": 80},
                   {"id": "time", "label": "Time", "width": 60}]
        rows = [{"_separator": True, "label": "GT3"},
                {"num": "123", "time": "1:23.4"}, {"num": "1", "time": "0:20.1"}]
        widget = Rows(columns, rows)
        try:
            render(widget)
            self.assertEqual(widget.width(), 900)
            self.assertEqual(widget.height(), 4 * core.ROW_H + 2 * core.PAD_Y)
            self.assertEqual([c["width"] for c in widget.columns], [80, 60])
            self.assertEqual((widget.x(), widget.y()), (123, 45))
        finally:
            widget.close()

    def test_existing_bar_retains_geometry_when_values_change(self):
        columns = [{"id": "value", "label": "Value", "width": 80}]
        widget = Bar(columns, [("value", "F 89.6 (10.0)", core.CLR_WHITE)])
        try:
            render(widget)
            self.assertEqual((widget.width(), widget.height()), (900, 20))
            widget.cells = [("value", "F 0", core.CLR_WHITE)]
            render(widget)
            self.assertEqual((widget.width(), widget.height()), (900, 20))
            self.assertEqual((widget.x(), widget.y()), (123, 45))
            self.assertEqual(widget.font_normal.pointSize(), 12)
        finally:
            widget.close()

    def test_existing_graphic_indicators_keep_original_configured_sizes(self):
        from hr import HR
        from wind import Wind
        from tyres import Tyres
        from alert import Alert
        widgets = [HR(), Wind(), Tyres(), Alert()]
        alert = widgets[-1]
        alert.activation_delay_s = 0
        alert._compute_alert = lambda: None
        alert._resolve_mode = lambda result: ("alert", 1, {})
        core.telemetry.update(WindVel=10)
        with patch("heart.latest_bpm", return_value=127):
            try:
                for widget in widgets:
                    position = widget.pos()
                    font = widget.font_normal.pointSize()
                    render(widget)
                    size = widget.size()
                    render(widget)
                    self.assertEqual(widget.size(), size)
                    self.assertEqual(widget.pos(), position)
                    self.assertEqual(widget.font_normal.pointSize(), font)
                for widget in widgets:
                    settings = self.cfg["windows"][widget._key]
                    self.assertEqual((widget.width(), widget.height()), (settings["width"], settings["height"]))
            finally:
                for widget in widgets:
                    widget.close()

    def test_existing_racechat_panel_keeps_original_geometry(self):
        from racechat import PassivePanel
        from racechat_service import Message
        widget = PassivePanel()
        widget._content_width_limit = 400
        widget.resize(440, 480)
        widget.move(123, 45)

        def paint():
            for _ in range(2):
                image = QImage(widget.size(), QImage.Format.Format_ARGB32)
                widget.render(image)

        try:
            paint()
            empty_height = widget.height()
            self.assertEqual(empty_height, 480)
            self.assertEqual(widget.width(), 440)
            for idx in range(6):
                widget.messages.append(Message("Discord", "channel", "author", "A readable message " * 10, str(idx), True))
            paint()
            self.assertEqual(widget.height(), empty_height)
            self.assertEqual(widget.width(), 440)
            self.assertEqual(len(widget.messages), 6)
            self.assertEqual((widget.x(), widget.y()), (123, 45))
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
