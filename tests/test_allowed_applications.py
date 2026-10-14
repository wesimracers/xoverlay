"""Exception/launcher tests; all activation and discovery calls are mocked."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import json
import ast
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from PyQt6.QtWidgets import QApplication
from headless_widgets import APP
import allowed_applications as allowed
import administrative_setup
import manager
import race_protection


class AllowedTests(unittest.TestCase):
    def test_selected_executable_is_an_exact_path_exception(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "Notes.exe"; file.write_bytes(b"test")
            entry = allowed.from_executable(file)
            names, paths = allowed.guard_exceptions([entry])
            self.assertEqual(names, [])
            self.assertEqual(paths, [str(file.resolve())])
    def test_invalid_targets_and_duplicate_entries_are_rejected(self):
        valid = {"label": "Music", "process": "AppleMusic.EXE", "target": "aumid:Apple.Family_abcd!App", "path": ""}
        self.assertEqual(allowed.normalize([valid, valid])[0]["process"], "AppleMusic")
        self.assertEqual(len(allowed.normalize([valid, valid])), 1)
        self.assertEqual(allowed.normalize([{**valid, "target": "aumid:../other!App"}]), [])
        self.assertEqual(allowed.normalize([{**valid, "target": "runas:powershell"}]), [])
    def test_deliberate_packaged_launch_uses_normal_open_without_runas(self):
        entry = {"label": "Music", "process": "AppleMusic", "path": "", "target": "aumid:Apple.Family_abcd!App"}
        with patch.object(allowed.os, "startfile") as launch:
            allowed.launch(entry)
        launch.assert_called_once_with("shell:AppsFolder\\Apple.Family_abcd!App")
    def test_broad_preset_without_installed_target_does_not_launch(self):
        with patch.object(allowed.os, "startfile") as launch, self.assertRaises(ValueError):
            allowed.launch(allowed.DEFAULT_ALLOWED[0])
        launch.assert_not_called()
    def test_global_mode_requests_helper_with_saved_exceptions(self):
        settings = {**race_protection.DEFAULTS, "block_elevation": True}
        self.assertIn("elevation", administrative_setup.wanted(settings))
        source = race_protection.RaceProtection({**settings, "enabled": False})
        self.assertEqual(source.status()["UAC"], "disabled")
        self.assertIn("saved exceptions suspended", source.status()["ApplicationMode"])
        with patch.object(source, "_runtime_status", return_value={"UAC": "activation failed; recovery pending"}):
            self.assertEqual(source.status()["UAC"], "activation failed; recovery pending")

    def test_runtime_suspends_and_restores_name_and_path_exceptions_without_launch(self):
        entries = allowed.normalize([allowed.DEFAULT_ALLOWED[0],
            {"label": "Custom", "process": "", "path": r"C:\Apps\custom.exe", "target": ""}])
        with tempfile.TemporaryDirectory() as folder, patch.object(race_protection.subprocess, "Popen") as launch:
            protection = race_protection.RaceProtection({"enabled": False})
            protection.root = Path(folder); protection.pause_file = protection.root / "pausar.flag"
            with patch.object(protection, "_administrative_flags", return_value=(False, False)):
                for global_mode in (False, True, False):
                    protection.configure({"enabled": False, "block_elevation": global_mode, "allowed_apps": entries})
                    runtime = json.loads((protection.root / "config.json").read_text())
                    expected = ([], []) if global_mode else allowed.guard_exceptions(entries)
                    self.assertEqual((runtime["AllowedProcessNames"], runtime["AllowedExecutablePaths"]), expected)
                    self.assertEqual(protection.settings["allowed_apps"], entries)
                    self.assertFalse(runtime["BlockInteractiveElevation"])
                with patch.object(protection, "_administrative_flags", return_value=(True, True)):
                    protection.process = object()
                    protection.configure({"enabled": True, "block_elevation": True, "allowed_apps": entries})
                    runtime = json.loads((protection.root / "config.json").read_text())
                    self.assertTrue(runtime["BlockInteractiveElevation"])
                    self.assertEqual(runtime["AllowedProcessNames"], [])
                    self.assertEqual(runtime["AllowedExecutablePaths"], [])
            launch.assert_not_called()
    def test_inventory_is_hidden_and_never_activates_an_app(self):
        result = Mock(stdout=json.dumps([{"label": "Notes", "process": "Notes", "target": "", "path": ""}]))
        with patch.object(allowed.subprocess, "run", return_value=result) as run, patch.object(allowed.os, "startfile") as activate:
            self.assertEqual(allowed.installed_apps()[0]["label"], "Notes")
        activate.assert_not_called()
        self.assertEqual(run.call_args.kwargs["creationflags"], allowed.subprocess.CREATE_NO_WINDOW)
        self.assertNotIn("runas", " ".join(run.call_args.args[0]).lower())
    def test_config_list_changes_wait_for_outer_save_and_cancel_discards_them(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg") as save, patch.object(race_protection, "monitors", return_value=[]):
            protection = Mock(); protection.administrative = None
            protection.diagnostic_text.return_value = "Simulated component status"
            protection.settings = race_protection.DEFAULTS.copy()
            protection.status.return_value = {"Mode": "waiting for game"}
            window = manager.ManagerWindow({}, {}, protection=protection)
            config = manager.ProtectionConfigDialog(window)
            dialog = manager.AllowedApplicationsDialog(config)
            try:
                self.assertTrue(config._protection_inputs["block_elevation"].isEnabled())
                before = len(dialog._entries)
                dialog._list.setCurrentRow(0); dialog._remove()
                dialog._save()
                self.assertEqual(len(config._allowed_apps), before - 1)
                self.assertIn(str(before - 1), config._allowed_button.text())
                protection.configure.assert_not_called()
                save.assert_not_called()
                config.reject()
                self.assertNotIn("allowed_apps", manager.core.cfg.get("race_protection", {}))
            finally:
                dialog.close(); config.close(); window.close(); APP.processEvents()
    def test_config_open_selected_uses_saved_mode_without_committing_pending_changes(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"), patch.object(race_protection, "monitors", return_value=[]):
            protection = Mock(); protection.administrative = None
            protection.diagnostic_text.return_value = "Simulated component status"
            protection.settings = race_protection.DEFAULTS.copy(); protection.status.return_value = {"Mode": "waiting"}
            window = manager.ManagerWindow({}, {}, protection=protection)
            config = manager.ProtectionConfigDialog(window); dialog = manager.AllowedApplicationsDialog(config)
            try:
                with patch.object(allowed, "launch") as activate:
                    dialog._list.setCurrentRow(4); dialog._open()
                    activate.assert_called_once()
                    self.assertIn("requested through Windows", dialog._status.text())
                    self.assertIn("saved protection mode", dialog._status.text())
                    protection.configure.assert_not_called()
            finally:
                dialog.close(); config.close(); window.close(); APP.processEvents()

    def test_manage_list_in_global_mode_preserves_mode_and_saves_added_entry(self):
        saved = {"windows": {}, "race_protection": {**race_protection.DEFAULTS, "block_elevation": True}}
        with patch.object(manager.core, "cfg", saved), patch.object(manager.core, "save_cfg") as save, \
             patch.object(race_protection, "monitors", return_value=[]), patch.object(allowed, "launch") as launch:
            protection = Mock(); protection.administrative = None
            protection.diagnostic_text.return_value = "Simulated status"
            protection.settings = race_protection.DEFAULTS.copy(); protection.status.return_value = {"Mode": "waiting"}
            window = manager.ManagerWindow({}, {}, protection=protection)
            config = manager.ProtectionConfigDialog(window); dialog = manager.AllowedApplicationsDialog(config)
            try:
                dialog._entries.append({"label": "Extra app", "process": "ExtraApp", "path": "", "target": ""})
                dialog._save()
                self.assertEqual(len(config._allowed_apps), 10)
                self.assertTrue(config._protection_inputs["block_elevation"].isChecked())
                self.assertEqual(len(manager.core.cfg["race_protection"]["allowed_apps"]), 9)
                save.assert_not_called(); protection.configure.assert_not_called()
                config._save_and_close()
                self.assertEqual(len(manager.core.cfg["race_protection"]["allowed_apps"]), 10)
                self.assertTrue(manager.core.cfg["race_protection"]["block_elevation"])
                launch.assert_not_called()
            finally:
                dialog.close(); config.close(); window.close(); APP.processEvents()

    def test_mode_save_reopen_restart_and_cancel_preserve_saved_list(self):
        entries = allowed.normalize(allowed.DEFAULT_ALLOWED)
        initial = {"windows": {}, "race_protection": {**race_protection.DEFAULTS, "allowed_apps": entries}}
        source = Path(__file__).resolve().parents[1] / "main/core.py"
        save_node = next(node for node in ast.parse(source.read_text(encoding="utf-8-sig")).body
                         if isinstance(node, ast.FunctionDef) and node.name == "save_cfg")
        persistence = {"os": os, "json": json, "_log": self.fail}
        exec(compile(ast.Module(body=[save_node], type_ignores=[]), str(source), "exec"), persistence)
        def save_actual_config():
            persistence.update(cfg=manager.core.cfg, CONFIG_FILE=manager.core.CONFIG_FILE)
            persistence["save_cfg"]()
        with tempfile.TemporaryDirectory() as folder, patch.object(manager.core, "cfg", initial), \
             patch.object(manager.core, "CONFIG_FILE", str(Path(folder) / "overlay.json"), create=True), \
             patch.object(manager.core, "save_cfg", side_effect=save_actual_config), \
             patch.object(race_protection, "monitors", return_value=[]), patch.object(allowed, "launch") as launch:
            protection = Mock(); protection.administrative = None
            protection.diagnostic_text.return_value = "Simulated status"
            protection.settings = race_protection.DEFAULTS.copy(); protection.status.return_value = {"Mode": "waiting"}
            window = manager.ManagerWindow({}, {}, protection=protection)
            try:
                for global_mode in (True, False, True):
                    dialog = manager.ProtectionConfigDialog(window)
                    self.assertTrue(dialog._allowed_button.isEnabled())
                    self.assertTrue(dialog._allow_mode.isEnabled())
                    self.assertTrue(dialog._protection_inputs["block_elevation"].isEnabled())
                    if global_mode:
                        dialog._protection_inputs["block_elevation"].click()
                    else:
                        dialog._allow_mode.click()
                    self.assertEqual(dialog._allow_mode.isChecked(), not global_mode)
                    self.assertEqual(dialog._protection_inputs["block_elevation"].isChecked(), global_mode)
                    self.assertEqual(dialog._allowed_apps, entries)
                    dialog._save_and_close()
                    if global_mode:
                        self.assertTrue(protection.configure.call_args.kwargs["request_setup"])
                    persisted = json.loads(Path(manager.core.CONFIG_FILE).read_text())
                    self.assertEqual(persisted["race_protection"]["allowed_apps"], entries)
                    self.assertEqual(persisted["race_protection"]["block_elevation"], global_mode)
                    # Reload persisted data as a new process would.
                    manager.core.cfg = persisted
                    reopened = manager.ProtectionConfigDialog(window)
                    self.assertEqual(reopened._protection_inputs["block_elevation"].isChecked(), global_mode)
                    self.assertEqual(reopened._allowed_apps, entries)
                    (reopened._allow_mode if global_mode else reopened._protection_inputs["block_elevation"]).click()
                    reopened.reject(); reopened.close(); dialog.close()
                    self.assertEqual(manager.core.cfg["race_protection"]["block_elevation"], global_mode)
                launch.assert_not_called()
            finally:
                window.close(); APP.processEvents()


if __name__ == "__main__":
    unittest.main()
