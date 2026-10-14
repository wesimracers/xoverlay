import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from class_names import CAR_PATH_CLASSES, class_labels


class ClassNameTests(unittest.TestCase):
    def test_every_bundled_category_and_arbitrary_class_ids(self):
        for idx, (path, expected) in enumerate(CAR_PATH_CLASSES.items()):
            with self.subTest(path=path):
                cid = 10000 + idx
                self.assertEqual(class_labels([{"CarClassID": cid, "CarPath": path}]), {cid: expected})

    def test_simulator_name_precedence_unknown_models_and_missing_metadata(self):
        self.assertEqual(class_labels([
            {"CarClassID": 1, "CarPath": "dallarap217", "CarClassName": "Full Class"},
            {"CarClassID": 1, "CarPath": "dallarap217", "CarClassShortName": " Custom Class "},
            {"CarClassID": 2, "CarScreenName": "New Formula Category"},
            {"CarClassID": 3, "CarScreenNameShort": "New Oval Category"},
            {"CarClassID": 4},
            {"CarClassID": -1, "CarClassShortName": "Invalid"},
            {"CarClassID": 5, "CarIsPaceCar": True},
        ]), {1: "Custom Class", 2: "New Formula Category", 3: "New Oval Category", 4: "CLASS 4"})

    def test_path_normalization_and_custom_mixed_class(self):
        self.assertEqual(class_labels([
            {"CarClassID": 1, "CarPath": "Dallara-P217"},
            {"CarClassID": 1, "CarPath": "Ferrari296GT3"},
            {"CarClassID": 2, "CarPath": "porsche9922cup"},
        ]), {1: "GT3 / LMP2", 2: "Porsche Cup"})

    def test_both_widgets_use_the_same_labels(self):
        from headless_widgets import core, basic_data, set_data, render, Standings
        from longest_sector import LongestSector
        from sector_timing import SectorHistory
        telemetry, session = basic_data()
        drivers = session["DriverInfo"]["Drivers"]
        for driver, cid, path in zip(drivers, [4091, 2523, 4093],
                                     ["ferrari296gt3", "dallarap217", "porsche9922cup"]):
            driver.update(CarClassID=cid, CarPath=path, CarClassShortName=None)
        telemetry["CarIdxClassPosition"] = [1, 1, 1]
        set_data(telemetry, session)
        old_history = getattr(core, "sector_history", None)
        core.sector_history = SectorHistory()
        widgets = [Standings(), LongestSector()]
        try:
            for widget in widgets:
                render(widget)
                labels = [r["label"].split(" · ")[0] for r in widget._last_rows if r.get("_separator")]
                self.assertEqual(labels, ["GT3", "LMP2", "Porsche Cup"] if isinstance(widget, Standings) else ["GT3"])
        finally:
            for widget in widgets:
                widget.close()
            core.sector_history = old_history


if __name__ == "__main__":
    unittest.main()
