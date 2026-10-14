"""Verify real Qt pixels, telemetry failure handling and manager integration."""

import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from headless_widgets import core, render, set_data, APP
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QLabel
from rpm import RPM
from rpm_state import car_key, resolve_max_rpm, rpm_state, seed_rpm_config
import manager

ROOT = Path(__file__).resolve().parents[1]


def info(path="car_a", redline=8000):
    return {"DriverCarIdx": 0, "DriverCarRedLine": redline,
            "DriverCarSLShiftRPM": 6000, "DriverCarSLBlinkRPM": 7000,
            "Drivers": [{"CarIdx": 0, "CarPath": path, "CarID": 123}]}


class RPMTests(unittest.TestCase):
    def setUp(self):
        self.cfg = copy.deepcopy(core.cfg)
        self.connected = core.ir.is_connected
        core.cfg = {"windows": {}, "rpm_settings": {}}
        self.telemetry = {"RPM": 4000, "IsOnTrack": True, "IsReplayPlaying": False}
        self.session = {"DriverInfo": info()}
        set_data(self.telemetry, self.session)
        core.ir.is_connected = True
        self.widget = RPM()
        self.widget._vis_timer.stop()

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        APP.processEvents()
        core.cfg = self.cfg
        core.ir.is_connected = self.connected

    def image_at(self, rpm):
        self.telemetry["RPM"] = rpm
        self.widget.update_data()
        return render(self.widget)

    def test_initial_geometry_and_exact_half_fill_without_text_or_padding(self):
        image = self.image_at(4000)
        self.assertEqual((image.width(), image.height()), (600, 10))
        yellow = (255, 255, 0)
        bg = (10, 10, 10)
        self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], yellow)
        self.assertEqual(image.pixelColor(299, 9).getRgb()[:3], yellow)
        self.assertEqual(image.pixelColor(300, 0).getRgb()[:3], bg)
        self.assertEqual(image.pixelColor(599, 9).getRgb()[:3], bg)
        self.assertEqual({image.pixelColor(x, y).getRgb()[:3] for x in range(600) for y in range(10)},
                         {yellow, bg})

    def test_color_progression_zero_maximum_and_clamping(self):
        for rpm, percent, rgb in ((0, 0, (10, 10, 10)), (800, 10, (51, 255, 0)),
                                  (4000, 50, (255, 255, 0)), (7200, 90, (255, 51, 0)),
                                  (8000, 100, (255, 0, 0)), (12000, 100, (255, 0, 0)),
                                  (-1, 0, (10, 10, 10))):
            with self.subTest(rpm=rpm):
                image = self.image_at(rpm)
                self.assertEqual(self.widget._last_payload["percent"], percent)
                self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], rgb)

    def test_invalid_rpm_and_disconnect_clear_previous_fill(self):
        self.image_at(8000)
        for value in (None, float("nan"), float("inf"), "bad", True):
            with self.subTest(value=value):
                image = self.image_at(value)
                self.assertEqual(self.widget._last_payload["status"], "missing_rpm")
                self.assertEqual(image.pixelColor(0, 0).getRgb()[:3], (10, 10, 10))
        with patch.object(core, "begin_frame", return_value=False):
            self.widget.update_data()
        self.assertEqual(self.widget._last_payload["status"], "disconnected")
        self.assertEqual(self.widget._last_payload["percent"], 0)

    def test_redline_not_shift_lights_or_live_peak_and_no_stale_car_limit(self):
        self.image_at(4000)
        self.assertEqual(self.widget._last_payload["max_rpm"], 8000)
        self.session["DriverInfo"] = info("car_b", 10000)
        self.image_at(4000)
        self.assertEqual(self.widget._last_payload["percent"], 40)
        self.session["DriverInfo"] = info("car_c", None)
        self.image_at(9000)
        self.assertEqual(self.widget._last_payload["status"], "missing_max_rpm")
        self.assertIsNone(self.widget._last_payload["max_rpm"])

    def test_per_car_override_switch_and_auto_recovery(self):
        settings = core.cfg["rpm_settings"]
        settings["max_rpm_by_car"]["path:car_a"] = 10000
        self.image_at(5000)
        self.assertEqual(self.widget._last_payload["percent"], 50)
        self.assertEqual(self.widget._last_payload["max_rpm_source"], "car_override")
        self.session["DriverInfo"] = info("car_b")
        self.image_at(4000)
        self.assertEqual(self.widget._last_payload["max_rpm_source"], "DriverCarRedLine")
        self.session["DriverInfo"] = info("car_a", None)
        self.image_at(5000)
        self.assertEqual(self.widget._last_payload["percent"], 50)
        settings["max_rpm_by_car"].clear()
        self.image_at(5000)
        self.assertEqual(self.widget._last_payload["status"], "missing_max_rpm")

    def test_invalid_limits_never_use_shift_lights(self):
        for invalid in (None, 0, -2, float("nan"), float("inf"), "bad", True):
            with self.subTest(invalid=invalid):
                state = rpm_state(5000, info(redline=invalid), {"max_rpm_by_car": {"path:car_a": invalid}})
                self.assertEqual(state["status"], "missing_max_rpm")
                self.assertEqual(state["percent"], 0)
        self.assertEqual(car_key({"DriverCarIdx": 2, "Drivers": [{"CarIdx": 2, "CarID": 44}]}), "id:44")
        self.assertIsNone(car_key({"Drivers": [{"CarIdx": 0, "CarPath": "car_a"}]}))

    def test_real_multicar_session_fixtures_use_client_redline(self):
        sessions = json.loads((ROOT / "tests/fixtures/rpm-cars.json").read_text(encoding="utf-8"))
        self.assertTrue(sessions)
        limits = set()
        for index, session in enumerate(sessions):
            driver_info = session["DriverInfo"]
            maximum, source = resolve_max_rpm(driver_info, {})
            self.assertEqual(maximum, driver_info["DriverCarRedLine"], str(index))
            self.assertEqual(source, "DriverCarRedLine")
            limits.add(maximum)
            if driver_info.get("DriverCarIdx", -1) >= 0:
                self.assertIsNotNone(car_key(driver_info), str(index))
        self.assertGreater(len(limits), 5)

    def test_visibility_follows_enable_driving_garage_and_connection(self):
        self.assertTrue(self.widget._should_be_visible())
        window = core.cfg["windows"]["rpm"]
        window["enabled"] = False
        self.assertFalse(self.widget._should_be_visible())
        window["enabled"] = True
        self.telemetry["IsOnTrack"] = False
        self.assertFalse(self.widget._should_be_visible())
        window["show_in_garage"] = True
        self.assertTrue(self.widget._should_be_visible())
        core.ir.is_connected = False
        self.assertFalse(self.widget._should_be_visible())

    def test_manager_preserves_thin_height_updates_timer_and_geometry_live(self):
        meta = next(m for m in manager.WIDGET_DEFS if m["key"] == "rpm")
        timer = QTimer()
        dialog = manager.WidgetConfigDialog(None, meta, self.widget, timer)
        try:
            self.assertEqual(dialog._inputs["_win_height"].value(), 10)
            self.assertEqual(dialog._inputs["_win_height"].minimum(), 1)
            self.assertNotIn("_win_font_size", dialog._inputs)
            dialog._inputs["_win_width"].setValue(720)
            dialog._inputs["_cfg_update_ms"].setValue(25)
            dialog._rpm_max_input.setValue(10000)
            self.widget.move(234, 456)
            with patch.object(core, "save_cfg") as save:
                dialog._save_and_close()
                save.assert_called_once()
            self.assertEqual((self.widget.width(), self.widget.height()), (720, 10))
            self.assertEqual((self.widget.x(), self.widget.y()), (234, 456))
            self.assertEqual(timer.interval(), 25)
            self.assertEqual(core.cfg["rpm_settings"]["max_rpm_by_car"], {"path:car_a": 10000})
            self.assertEqual(self.widget._last_payload["percent"], 40)
            image = render(self.widget)
            self.assertNotEqual(image.pixelColor(287, 0), image.pixelColor(288, 0))
        finally:
            dialog.close()

    def test_override_dialog_keeps_original_model_if_car_changes_while_open(self):
        meta = next(m for m in manager.WIDGET_DEFS if m["key"] == "rpm")
        dialog = manager.WidgetConfigDialog(None, meta, self.widget)
        try:
            dialog._rpm_max_input.setValue(10000)
            self.session["DriverInfo"] = info("car_b")
            with patch.object(core, "save_cfg"):
                dialog._save_and_close()
            self.assertEqual(core.cfg["rpm_settings"]["max_rpm_by_car"], {"path:car_a": 10000})
            self.assertEqual(self.widget._last_payload["max_rpm"], 8000)
        finally:
            dialog.close()

    def test_disconnected_dialog_does_not_bind_override_to_stale_car(self):
        core.ir.is_connected = False
        meta = next(m for m in manager.WIDGET_DEFS if m["key"] == "rpm")
        dialog = manager.WidgetConfigDialog(None, meta, self.widget)
        try:
            self.assertFalse(dialog._rpm_max_input.isEnabled())
            self.assertTrue(any("reopen Config" in label.text() for label in dialog.findChildren(QLabel)))
            with patch.object(core, "save_cfg"):
                dialog._save_and_close()
            self.assertEqual(core.cfg["rpm_settings"]["max_rpm_by_car"], {})
        finally:
            dialog.close()

    def test_legacy_config_load_seeds_defaults_preserving_custom_settings(self):
        cfg = {"windows": {"rpm": {"height": 6}, "input": {"width": 820}},
               "rpm_settings": {"max_rpm_by_car": {"path:car_a": 10000}}}
        seed_rpm_config(cfg)
        self.assertEqual(cfg["windows"]["rpm"]["height"], 6)
        self.assertEqual(cfg["windows"]["input"], {"width": 820})
        self.assertEqual(cfg["rpm_settings"]["max_rpm_by_car"], {"path:car_a": 10000})
        # Execute only the production loader, avoiding core's archive startup side effects.
        tree = ast.parse((ROOT / "main/core.py").read_text(encoding="utf-8"))
        loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_cfg")
        with tempfile.TemporaryDirectory() as temp:
            config_path = Path(temp) / "overlay.json"
            config_path.write_text(json.dumps({"windows": {"input": {"width": 820}}}), encoding="utf-8")
            namespace = {"json": json, "os": __import__("os"), "CONFIG_FILE": str(config_path),
                         "seed_rpm_config": seed_rpm_config, "sector_columns": lambda columns: columns}
            exec(compile(ast.Module(body=[loader], type_ignores=[]), "core.load_cfg", "exec"), namespace)
            loaded = namespace["load_cfg"]()
        self.assertEqual(loaded["windows"]["rpm"]["width"], 600)
        self.assertEqual(loaded["windows"]["rpm"]["height"], 10)


if __name__ == "__main__":
    unittest.main()
