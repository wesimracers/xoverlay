import copy
import unittest

from headless_widgets import Weather, basic_data, core, render, set_data
from weather import _RUBBER_MAP, _rubber_label, _track_wetness_label
from weather_columns import WEATHER_COLUMNS, weather_columns


class WeatherWetnessTests(unittest.TestCase):
    def test_sdk_wetness_levels_and_unknown(self):
        self.assertEqual(_track_wetness_label(1), "dry")
        self.assertEqual(_track_wetness_label(4), "lightly wet")
        self.assertEqual(_track_wetness_label(7), "extremely wet")
        self.assertEqual(_track_wetness_label(0), "")
        self.assertEqual(_track_wetness_label(99), "")
        self.assertEqual(_track_wetness_label(None), "")
        self.assertEqual(_track_wetness_label("light wet"), "light wet")

    def test_wet_cell_keeps_yes_no_and_condition_has_its_own_divider(self):
        telemetry, session = basic_data()
        telemetry.update(WeatherDeclaredWet=True, TrackWetness=4, Precipitation=0.2)
        set_data(telemetry, session)
        widget = Weather()
        cells = []
        original_draw = widget._draw_row

        def capture(painter, current):
            cells.clear()
            cells.extend(current)
            original_draw(painter, current)

        widget._draw_row = capture
        try:
            image = render(widget)
            self.assertEqual(next(text for cid, text, _color in cells if cid == "wet"),
                             'WET: YES')
            self.assertEqual(next(text for cid, text, _color in cells if cid == "condition"),
                             'Lightly Wet')
            self.assertEqual(widget._last_payload["Wet"], 'YES')
            self.assertEqual(widget._last_payload["TrackWetness"], 'lightly wet')
            before_condition = widget.columns[:next(i for i, col in enumerate(widget.columns)
                                                    if col["id"] == "condition")]
            divider_x = core.PAD_X + sum(col["width"] for col in before_condition) + len(before_condition) - 1
            self.assertEqual(image.pixelColor(divider_x, core.PAD_Y), core.CLR_GRID)
            telemetry["WeatherDeclaredWet"] = False
            telemetry["TrackWetness"] = 2
            render(widget)
            self.assertEqual(next(text for cid, text, _color in cells if cid == "wet"), "WET: NO")
            self.assertEqual(next(text for cid, text, _color in cells if cid == "condition"), "Mostly Dry")
            telemetry["WeatherDeclaredWet"] = False
            telemetry["TrackWetness"] = 0
            render(widget)
            self.assertEqual(next(text for cid, text, _color in cells if cid == "wet"), "WET: NO")
            self.assertEqual(next(text for cid, text, _color in cells if cid == "condition"), "—")
            telemetry["WeatherDeclaredWet"] = None
            telemetry["TrackWetness"] = 1
            render(widget)
            self.assertEqual(next(text for cid, text, _color in cells if cid == "wet"), "WET: —")
            self.assertEqual(next(text for cid, text, _color in cells if cid == "condition"), "Dry")
        finally:
            widget.close()

    def test_narrow_wet_column_and_window_are_respected(self):
        old_settings = copy.deepcopy(core.cfg["weather_settings"])
        old_window = copy.deepcopy(core.cfg["windows"]["weather"])
        widget = None
        try:
            next(col for col in core.cfg["weather_settings"]["columns"] if col["id"] == "wet")["width"] = 60
            core.cfg["windows"]["weather"].update(x=2939, width=500)
            widget = Weather()
            self.assertEqual(next(col["width"] for col in widget.columns if col["id"] == "wet"), 60)
            self.assertEqual(widget.x(), 2939)
            self.assertEqual(widget.width(), 500)
            widget.apply_font()
            render(widget)
            self.assertEqual(next(col["width"] for col in widget.columns if col["id"] == "wet"), 60)
            self.assertEqual(widget.x(), 2939)
            self.assertEqual(widget.width(), 500)
        finally:
            if widget is not None:
                widget.close()
            core.cfg["weather_settings"] = old_settings
            core.cfg["windows"]["weather"] = old_window

    def test_rubber_abbreviations_and_unknown_values_fit_seven_characters(self):
        for raw, expected in _RUBBER_MAP.items():
            with self.subTest(raw=raw):
                self.assertEqual(_rubber_label(raw), expected)
                self.assertLessEqual(len(_rubber_label(raw)), 7)
        self.assertEqual(_rubber_label("  Custom long state usage  "), "CUSTOM")
        self.assertEqual(_rubber_label("short"), "SHORT")
        self.assertEqual(_rubber_label(""), "")

    def test_legacy_columns_split_default_space_and_preserve_custom_settings(self):
        old = [dict(col) for col in WEATHER_COLUMNS if col["id"] != "condition"]
        wet = next(col for col in old if col["id"] == "wet")
        wet.update(width=360, label="Custom", enabled=False)
        original = copy.deepcopy(old)
        upgraded = weather_columns(old)
        self.assertEqual(old, original)
        self.assertEqual([col["id"] for col in upgraded],
                         ["rubber", "temp", "track", "wet", "condition", "prec"])
        self.assertEqual(upgraded[3], dict(wet, width=90))
        self.assertFalse(upgraded[4]["enabled"])
        self.assertEqual(sum(col["width"] for col in upgraded) + len(upgraded),
                         sum(col["width"] for col in old) + len(old))
        self.assertEqual(weather_columns(upgraded), upgraded)
        wet["width"] = 200
        custom = weather_columns(old)
        self.assertEqual(custom[3]["width"], 90)
        self.assertEqual(custom[4]["width"], 109)
        wet["width"] = 60
        self.assertEqual(weather_columns(old)[3]["width"], 60)

    def test_hub_column_editor_keeps_condition_label_blank(self):
        from manager import ColumnsEditor
        editor = ColumnsEditor("weather")
        try:
            condition = next(col for col in editor.get_columns() if col["id"] == "condition")
            self.assertEqual(condition["label"], "")
            self.assertTrue(condition["enabled"])
        finally:
            editor.close()


if __name__ == "__main__":
    unittest.main()
