import copy
import unittest

from PyQt6.QtGui import QFont, QFontMetrics
from headless_widgets import Standings, basic_data, core, render, set_data
from last_lap_ranking import format_lap_millis, format_top_lap_entry, top_last_laps


class StandingsTopLapsTests(unittest.TestCase):
    def test_millisecond_format_and_entry_order(self):
        self.assertEqual(format_lap_millis(98.5), "1:38.500")
        self.assertEqual(format_lap_millis(59.9996), "1:00.000")
        self.assertEqual(format_top_lap_entry({
            "num": "23", "pos": "4", "bestLap": "1:38.500", "tyre": "H",
        }), "#23 (4) 1:38.500 H")

    def test_ranker_excludes_invalid_laps_and_pace_car(self):
        drivers = {idx: {"UserName": f"Driver {idx}"} for idx in range(7)}
        drivers[6]["CarIsPaceCar"] = True
        laps = [92.3, 88.1, -1, 88.1, float("nan"), 100.0, 70.0]
        rows = top_last_laps(drivers, laps, [0, 1, 0, 0, 1, 1, 0])
        self.assertEqual([r["_idx"] for r in rows], [1, 3, 0])
        self.assertEqual([r["compound"] for r in rows], [1, 0, 0])

    def test_top_three_appears_under_each_class_and_regular_rows_remain(self):
        telemetry, session = basic_data()
        drivers = session["DriverInfo"]["Drivers"]
        drivers.append({"CarIdx": 3, "CarClassID": 2, "CarNumber": "44"})
        drivers.append({"CarIdx": 4, "CarClassID": 2, "CarNumber": "55"})
        telemetry["CarIdxClassPosition"] = [2, 3, 1, 2, 1]
        telemetry["CarIdxLastLapTime"] = [101.2, 99.3, 100.5, 120.0, 118.0]
        telemetry["CarIdxTireCompound"] = [0, 1, 0, 1, 0]
        set_data(telemetry, session)
        old_tire_letter = core.tire_letter
        old_window = copy.deepcopy(core.cfg["windows"]["standings"])
        core.tire_letter = lambda compound: {0: "H", 1: "W"}.get(compound, "")
        widget = Standings()
        try:
            image = render(widget)
            sections = [r for r in widget._last_rows if r.get("_separator")]
            self.assertEqual(len(sections), 2)
            self.assertEqual([r["_idx"] for r in sections[0]["_top_laps"]], [1, 2, 0])
            self.assertEqual([r["pos"] for r in sections[0]["_top_laps"]], ["3", "1", "2"])
            self.assertEqual([r["bestLap"] for r in sections[0]["_top_laps"]],
                             ["1:39.300", "1:40.500", "1:41.200"])
            self.assertEqual([r["tyre"] for r in sections[0]["_top_laps"]], ["W", "H", "H"])
            self.assertEqual(format_top_lap_entry(sections[0]["_top_laps"][0]),
                             "#2 (3) 1:39.300 W")
            self.assertEqual([r["_idx"] for r in sections[1]["_top_laps"]], [4, 3])
            self.assertEqual(image.pixelColor(5, 23).getRgb()[:3], (255, 224, 178))
            font = QFont(widget.font_normal)
            font.setPointSize(max(8, font.pointSize() - 2))
            max_label_width = max(QFontMetrics(font).horizontalAdvance(format_top_lap_entry(lap))
                                  for section in sections for lap in section["_top_laps"])
            self.assertGreaterEqual((widget.width() - 2 * core.PAD_X) / 3,
                                    max_label_width + 8)
            self.assertTrue(any(r.get("_idx") == 0 for r in widget._last_rows))
            self.assertEqual(widget.height(), min(widget._max_h, 3 + 3 + 18 * 11))

            widget.show_top_last_laps = False
            render(widget)
            self.assertNotIn("_top_laps", next(r for r in widget._last_rows if r.get("_separator")))
        finally:
            core.tire_letter = old_tire_letter
            core.cfg["windows"]["standings"] = old_window
            widget.close()

    def test_empty_top_lap_strip_has_no_message(self):
        telemetry, session = basic_data()
        telemetry["CarIdxLastLapTime"] = [-1, 0, -1]
        set_data(telemetry, session)
        widget = Standings()
        try:
            image = render(widget)
            section = next(r for r in widget._last_rows if r.get("_separator"))
            self.assertEqual(section["_top_laps"], [])
            strip_top = core.PAD_Y + core.ROW_H
            dividers = [core.PAD_X + round(j * (image.width() - 2 * core.PAD_X) / 3)
                        for j in (1, 2)]
            orange = (255, 224, 178)
            for y in range(strip_top + 2, strip_top + core.ROW_H - 2):
                for x in range(core.PAD_X + 5, image.width() - core.PAD_X - 5):
                    if all(abs(x - divider) > 2 for divider in dividers):
                        self.assertEqual(image.pixelColor(x, y).getRgb()[:3], orange)
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
