"""No live protection, dialogs or registry/firewall writes during this suite."""
import json
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
import race_protection
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QRect, QPoint
import manager

APP = QApplication.instance() or QApplication([])


class ProtectionTests(unittest.TestCase):
    def test_disabled_configuration_is_persisted_without_launch(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(race_protection.subprocess, "Popen") as launch:
            protection = race_protection.RaceProtection({"enabled": False})
            protection.root = Path(folder)
            protection.pause_file = protection.root / "pausar.flag"
            protection.configure({"enabled": False, "input_grace_ms": 1900, "alert_monitor": "\\\\.\\DISPLAY5"})
            launch.assert_not_called()
            self.assertTrue(protection.pause_file.exists())
            config = json.loads((protection.root / "config.json").read_text())
            self.assertEqual(config["UserInputGraceMs"], 2000)
            self.assertEqual(config["AlertMonitor"], "\\\\.\\DISPLAY5")
            self.assertTrue(config["RouteAlways"])
            self.assertFalse(config["BlockInteractiveElevation"])
            self.assertEqual(protection.status()["Mode"], "disabled")
            protection.configure({"enabled": False, "block_elevation": True})
            self.assertTrue(protection.settings["block_elevation"])
            self.assertFalse(json.loads((protection.root / "config.json").read_text())["BlockInteractiveElevation"])
            launch.assert_not_called()

    def test_close_releases_only_own_lease_without_killing_process(self):
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection()
            protection.root = Path(folder)
            own = protection.root / f"owner-{os.getpid()}.json"
            other = protection.root / "owner-99999.json"
            own.touch(); other.touch()
            protection.process = Mock()
            protection.close()
            self.assertFalse(own.exists())
            self.assertTrue(other.exists())
            protection.process.terminate.assert_not_called()
            protection.process.kill.assert_not_called()

    def test_missing_component_is_silent_and_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection()
            protection.source = Path(folder)
            protection.start()
            self.assertIn("unavailable", protection.status()["Mode"])

    def test_protection_config_save_and_apply_without_popup(self):
        display = {"device": "\\\\.\\DISPLAY5", "label": "DISPLAY5 · upper", "upper": True}
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg") as save, patch.object(race_protection, "monitors", return_value=[display]):
            protection = Mock()
            protection.settings = race_protection.DEFAULTS.copy()
            protection.pause_file.exists.return_value = False
            protection.status.return_value = {"Mode": "waiting for game", "Firewall": "pending"}
            protection.diagnostic_text.return_value = "Simulated diagnostics"
            win = manager.ManagerWindow({}, {}, protection=protection)
            dialog = manager.ProtectionConfigDialog(win)
            try:
                dialog._protection_inputs["enabled"].setChecked(False)
                dialog._protection_inputs["redirect_always"].setChecked(False)
                dialog._protection_inputs["block_elevation"].setChecked(False)
                dialog._protection_inputs["input_grace_ms"].setValue(4000)
                dialog._alert_monitor.setCurrentIndex(1)
                dialog._save_and_close()
                stored = manager.core.cfg["race_protection"]
                self.assertFalse(stored["enabled"])
                self.assertFalse(stored["redirect_always"])
                self.assertFalse(stored["block_elevation"])
                self.assertEqual(stored["input_grace_ms"], 4000)
                self.assertEqual(stored["alert_monitor"], display["device"])
                save.assert_called_once()
                protection.configure.assert_called_once_with(stored)
            finally:
                dialog.close(); win.close(); APP.processEvents()

    def test_degraded_components_are_visible_without_false_restore_warning(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"):
            protection = Mock()
            protection.settings = race_protection.DEFAULTS.copy()
            protection.pause_file.exists.return_value = False
            protection.status.return_value = {"Mode": "degraded", "Windows": "active", "Routing": "active, without activating windows",
                "Toasts": "not applied: access denied; install administrator helper", "Focus": "already configured",
                "Firewall": "administrator setup pending", "Pending": False, "Degraded": True}
            protection.diagnostic_text.return_value = "Component diagnostics"
            win = manager.ManagerWindow({}, {}, protection=protection)
            try:
                text = win._protection_label.text()
                self.assertIn("Protection: degraded", text)
                self.assertIn("Toasts: not applied: access denied", text)
                self.assertIn("Windows: active", text)
                self.assertIn("UAC: not blocked, including administrators", text)
                self.assertNotIn("restoration pending", text)
            finally:
                win.close(); APP.processEvents()


    def test_uac_limit_is_visible_for_active_and_legacy_status(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"):
            protection = Mock()
            protection.settings = race_protection.DEFAULTS.copy()
            protection.pause_file.exists.return_value = False
            protection.diagnostic_text.return_value = "Simulated diagnostics"
            for status in ({"Mode": "active", "Windows": "active", "Pending": False},
                           {"Mode": "active", "Windows": "active", "UAC": race_protection.UAC_STATUS},
                           {"Mode": "disabled"}):
                protection.status.return_value = status
                win = manager.ManagerWindow({}, {}, protection=protection)
                try:
                    self.assertIn("UAC: not blocked, including administrators", win._protection_label.text())
                    self.assertIn(f"Protection: {status['Mode']}", win._protection_label.text())
                finally:
                    win.close(); APP.processEvents()

    def test_diagnostics_do_not_equate_active_or_degraded_with_uac_protection(self):
        protection = race_protection.RaceProtection({"enabled": False})
        for mode in ("active", "degraded", "disabled"):
            with patch.object(protection, "status", return_value={"Mode": mode}):
                text = protection.diagnostic_text()
                self.assertIn("UAC: not blocked, including administrators", text)
                self.assertIn("optional global broker gate", text)
                self.assertIn("not UAC coverage", text)

    def test_protection_row_counts_and_has_matching_controls(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"):
            win = manager.ManagerWindow({}, {})
            try:
                panel = win.centralWidget()
                row = win._protection_row
                self.assertEqual(len(panel._rows), len(manager.WIDGET_DEFS) + 1)
                self.assertEqual(row._meta["label"], "Pop-up Protection")
                self.assertEqual(row._btn_cfg.text(), "Config")
                self.assertEqual(row._btn_toggle.text(), "ON")
                row._toggle()
                self.assertEqual(row._btn_toggle.text(), "OFF")
                self.assertFalse(manager.core.cfg["race_protection"]["enabled"])
                self.assertIn(f"/{len(panel._rows)}", panel._label.text())
            finally:
                win.close(); APP.processEvents()

    def test_all_rows_fit_without_scroll_on_current_and_shorter_displays(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"):
            for width, height in ((3440, 1440), (1920, 1080), (800, 500)):
                win = manager.ManagerWindow({}, {})
                try:
                    win._fit_rows_to_screen(QRect(0, 0, width, height))
                    win.show(); APP.processEvents()
                    self.assertLess(win.height(), height)
                    self.assertLess(win.width(), width)
                    for row in win.centralWidget()._rows:
                        for button in (row._btn_cfg, row._btn_toggle):
                            point = button.mapTo(win, QPoint())
                            self.assertTrue(win.rect().contains(point))
                            self.assertTrue(win.rect().contains(point + QPoint(button.width()-1, button.height()-1)))
                    if height == 500:
                        self.assertEqual(win.centralWidget()._columns, 2)
                finally:
                    win.close(); APP.processEvents()


if __name__ == "__main__":
    unittest.main()
