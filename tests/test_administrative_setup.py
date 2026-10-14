"""No consent, service, registry, network or visible window calls."""
import json
import hashlib
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
import administrative_setup as setup
import race_protection
import core
import racechat_profile_sync as profile_sync


class Backend:
    def __init__(self):
        self.ready = set()
        self.requests = []
        self.allowed = True
        self.code = 0
        self.confirm = True
    def current(self, feature):
        return feature in self.ready
    def can_request(self):
        return self.allowed
    def request(self, features, remove=False):
        self.requests.append((features, remove))
        if not self.code and self.confirm:
            self.ready = self.ready - features if remove else self.ready | features
        return self.code, "Simulated setup result"


class DeferredThread:
    queue = []
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.queue.append(self.target)


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.backend = Backend()
        self.now = 0
        self.controller = setup.AdministrativeSetup(self.backend, clock=lambda: self.now)
        self.settings = race_protection.DEFAULTS.copy()
        self.settings["allowed_apps"] = []
        DeferredThread.queue = []
        self.thread_patch = patch.object(setup.threading, "Thread", DeferredThread)
        self.sleep_patch = patch.object(setup.time, "sleep")
        self.thread_patch.start(); self.sleep_patch.start()
    def tearDown(self):
        self.sleep_patch.stop(); self.thread_patch.stop()
    def complete(self):
        DeferredThread.queue.pop(0)()
    def test_requirements_follow_enabled_features(self):
        self.assertEqual(setup.wanted(self.settings), {"firewall"})
        self.assertEqual(setup.wanted({**self.settings, "block_elevation": True}), {"firewall", "elevation"})
        self.assertEqual(setup.wanted({**self.settings, "enabled": False, "block_elevation": True}), set())
        self.assertIn("elevation", setup.wanted({**self.settings, "block_elevation": True, "allowed_apps": race_protection.DEFAULTS["allowed_apps"]}))
    def test_first_open_one_request_then_verified_ready(self):
        self.controller.begin(self.settings)
        self.assertTrue(self.controller.pending)
        self.assertFalse(self.controller.ready["firewall"])
        for _ in range(8):
            self.controller.begin(self.settings)
        self.assertEqual(len(DeferredThread.queue), 1)
        self.complete()
        self.assertFalse(self.controller.pending)
        self.assertTrue(self.controller.ready["firewall"])
        self.assertEqual(self.backend.requests, [({"firewall"}, False)])
    def test_current_helpers_do_not_request_consent(self):
        self.backend.ready = {"firewall"}
        self.controller.begin(self.settings)
        self.assertEqual(DeferredThread.queue, [])
        self.assertIn("runtime coverage", self.controller.status())
    def test_cancel_is_not_retried_until_explicit_retry(self):
        self.backend.code = 1223
        self.controller.begin(self.settings); self.complete()
        self.controller.begin(self.settings)
        self.assertFalse(self.controller.ready["firewall"])
        self.assertEqual(DeferredThread.queue, [])
        self.backend.code = 0
        self.controller.begin(self.settings, retry=True); self.complete()
        self.assertTrue(self.controller.ready["firewall"])
        self.assertEqual(len(self.backend.requests), 2)
    def test_explicit_retry_reprovisions_current_helper_for_durable_recovery_latch(self):
        self.backend.ready = {"firewall"}
        self.controller.begin(self.settings, retry=True)
        self.assertTrue(self.controller.pending)
        self.complete()
        self.assertEqual(self.backend.requests, [({"firewall"}, False)])
    def test_exit_zero_without_verified_helper_is_not_success(self):
        self.backend.confirm = False
        self.controller.begin(self.settings); self.complete()
        self.assertFalse(self.controller.ready["firewall"])
        self.assertIn("did not confirm", self.controller.status())
    def test_add_feature_after_attempt_requires_explicit_intent(self):
        self.controller.begin(self.settings); self.complete()
        changed = {**self.settings, "block_elevation": True}
        self.controller.begin(changed)
        self.assertEqual(DeferredThread.queue, [])
        self.controller.begin(changed, retry=True); self.complete()
        self.assertTrue(self.controller.ready["elevation"])
    def test_game_defers_without_consuming_attempt_then_resumes(self):
        self.backend.allowed = False
        self.controller.begin(self.settings)
        self.assertFalse(self.controller.pending)
        self.assertFalse(self.controller.attempted)
        self.assertIn("no permission request", self.controller.status())
        self.backend.allowed = True
        self.controller.begin(self.settings); self.complete()
        self.assertEqual(len(self.backend.requests), 1)
    def test_pending_timeout_does_not_send_another_request(self):
        self.controller.begin(self.settings)
        self.now = 61
        self.assertIn("no automatic retry", self.controller.status())
        self.controller.begin(self.settings, retry=True)
        self.assertEqual(len(DeferredThread.queue), 1)
    def test_explicit_setup_can_run_with_game_without_enabling_automatic_requests(self):
        self.backend.allowed = False
        self.controller.begin(self.settings)
        self.assertFalse(self.controller.pending)
        self.controller.begin(self.settings, retry=True, allow_running_game=True)
        self.assertTrue(self.controller.pending)
        self.controller.begin(self.settings, retry=True, allow_running_game=True)
        self.assertEqual(len(DeferredThread.queue), 1)
        self.complete()
        self.assertEqual(self.backend.requests, [({"firewall"}, False)])
    def test_deferred_removal_survives_prior_attempt(self):
        self.controller.begin(self.settings); self.complete()
        disabled = {**self.settings, "mute_toasts": False, "firewall_notifications": False}
        self.backend.allowed = False
        self.controller.begin(disabled, remove=True, retry=True)
        self.assertTrue(self.controller.deferred_remove)
        self.backend.allowed = True
        self.controller.begin(disabled); self.complete()
        self.assertEqual(self.backend.requests[-1], ({"firewall", "elevation"}, True))
        self.assertFalse(any(self.controller.ready.values()))
    def test_partial_failure_never_claims_elevation(self):
        self.settings["block_elevation"] = True
        self.backend.ready = {"firewall"}
        self.backend.code = 1
        self.controller.begin(self.settings); self.complete()
        self.assertTrue(self.controller.ready["firewall"])
        self.assertFalse(self.controller.ready["elevation"])
    def test_exception_clears_pending_and_prevents_retry_storm(self):
        with patch.object(self.backend, "request", side_effect=OSError("simulated denial")):
            self.controller.begin(self.settings); self.complete()
        self.assertFalse(self.controller.pending)
        self.assertIn("unavailable", self.controller.status())
        self.controller.begin(self.settings)
        self.assertEqual(DeferredThread.queue, [])
    def test_runtime_quiesces_privileged_leases_until_ready(self):
        self.settings["block_elevation"] = True
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection(self.settings)
            protection.root = Path(folder); protection.pause_file = protection.root / "pausar.flag"
            protection.administrative = self.controller
            protection.process = object()
            with patch.object(race_protection, "monitors", return_value=[]):
                protection.configure(self.settings)
                config = json.loads((protection.root / "config.json").read_text())
                self.assertFalse(config["BlockInteractiveElevation"])
                self.assertFalse(config["MuteAppToasts"])
                self.assertTrue(config["GeneralWindowGuard"])
                self.complete()
                protection.status()
                config = json.loads((protection.root / "config.json").read_text())
                self.assertTrue(config["BlockInteractiveElevation"])
                self.assertTrue(config["MuteAppToasts"])
    def test_setup_status_is_present_before_first_guard_status(self):
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection({"enabled": False})
            protection.root = Path(folder)
            protection.administrative = self.controller
            self.assertIn("Setup", protection.status())

    def test_save_global_mode_provisions_missing_helper_with_saved_apps_even_in_game(self):
        self.backend.ready = {"firewall"}
        self.backend.allowed = False
        self.controller.attempted = True
        settings = {**self.settings, "block_elevation": True, "allowed_apps": race_protection.DEFAULTS["allowed_apps"]}
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection(settings)
            protection.root = Path(folder); protection.pause_file = protection.root / "pausar.flag"
            protection.administrative = self.controller; protection.process = object()
            protection._last_admin_wanted = {"firewall"}
            protection.configure(settings, request_setup=True)
            self.assertTrue(self.controller.pending)
            runtime = json.loads((protection.root / "config.json").read_text())
            self.assertFalse(runtime["BlockInteractiveElevation"])
            self.assertEqual(runtime["AllowedProcessNames"], [])
            self.complete()
            self.assertEqual(self.backend.requests, [({"firewall", "elevation"}, False)])
            self.assertTrue(self.controller.ready["elevation"])
            status = protection.status()
            self.assertIn("runtime not confirmed", status["UAC"])
            self.assertTrue(json.loads((protection.root / "config.json").read_text())["BlockInteractiveElevation"])
            protection.configure({**settings, "block_elevation": False})
            runtime = json.loads((protection.root / "config.json").read_text())
            self.assertFalse(runtime["BlockInteractiveElevation"])
            self.assertIn("AppleMusic", runtime["AllowedProcessNames"])
            self.assertEqual(protection.settings["allowed_apps"], settings["allowed_apps"])

    def test_cancelled_global_setup_keeps_mode_no_prompt_storm_and_save_retries(self):
        self.backend.ready = {"firewall"}; self.backend.code = 1223
        settings = {**self.settings, "block_elevation": True, "allowed_apps": race_protection.DEFAULTS["allowed_apps"]}
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection(settings)
            protection.root = Path(folder); protection.pause_file = protection.root / "pausar.flag"
            protection.administrative = self.controller; protection.process = object()
            protection.configure(settings, request_setup=True); self.complete()
            for _ in range(8):
                protection.status(); protection.configure(settings)
            self.assertEqual(len(self.backend.requests), 1)
            self.assertEqual(DeferredThread.queue, [])
            self.assertTrue(protection.settings["block_elevation"])
            self.assertEqual(protection.settings["allowed_apps"], settings["allowed_apps"])
            self.assertFalse(json.loads((protection.root / "config.json").read_text())["BlockInteractiveElevation"])
            self.backend.code = 0
            protection.configure(settings, request_setup=True); self.complete(); protection.status()
            self.assertEqual(len(self.backend.requests), 2)
            self.assertTrue(self.controller.ready["elevation"])

    def test_global_save_while_other_setup_pending_waits_then_requests_elevation_once(self):
        with tempfile.TemporaryDirectory() as folder:
            protection = race_protection.RaceProtection(self.settings)
            protection.root = Path(folder); protection.pause_file = protection.root / "pausar.flag"
            protection.administrative = self.controller; protection.process = object()
            protection.configure(self.settings)
            changed = {**self.settings, "block_elevation": True, "mute_toasts": False, "firewall_notifications": False,
                       "allowed_apps": race_protection.DEFAULTS["allowed_apps"]}
            protection.configure(changed, request_setup=True)
            self.assertEqual(len(DeferredThread.queue), 1)
            self.complete()
            protection.status()
            self.assertEqual(len(DeferredThread.queue), 1)
            self.complete(); protection.status(); protection.status()
            self.assertEqual(self.backend.requests, [({"firewall"}, False), ({"elevation"}, False)])
            self.assertEqual(DeferredThread.queue, [])
            self.assertTrue(json.loads((protection.root / "config.json").read_text())["BlockInteractiveElevation"])
    def test_fresh_factory_does_not_import_personal_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(core, "CONFIG_FILE", str(Path(folder) / "overlay.json")):
            config = core.load_cfg()
            self.assertTrue(config["_fresh_factory_layout"])
            self.assertFalse(config["debug"])
            self.assertFalse(config["race_protection"]["block_elevation"])
            self.assertEqual(config["heart_settings"]["widget_url"], "")
            self.assertFalse((Path(folder) / "overlay.json").exists())
    def test_opted_in_frozen_sync_hook_uses_same_executable(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"APPDATA": folder}), patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", r"C:\Portable Folder\OverlayApp.exe"):
            profile_sync.ensure_logon_hook()
            files = list(Path(folder).rglob("*.cmd"))
            self.assertEqual(len(files), 1)
            text = files[0].read_text()
            self.assertIn('"C:\\Portable Folder\\OverlayApp.exe" --racechat-sync', text)
            self.assertNotIn("powershell", text.lower())
            self.assertNotIn("27b", text)
    def test_partial_native_setup_marker_cannot_claim_ready(self):
        with tempfile.TemporaryDirectory() as folder:
            backend = setup.WindowsBackend.__new__(setup.WindowsBackend)
            backend.sid = "S-1-5-21-123-456-789-1111"
            backend.program_files = Path(folder) / "code"
            backend.program_data = Path(folder) / "state"
            name, subfolder, metadata = setup.COMPONENTS["firewall"]
            code = backend.program_files / subfolder
            state = backend.program_data / subfolder
            code.mkdir(parents=True); state.mkdir(parents=True)
            binary = b"temporary test helper"
            (code / (name + ".exe")).write_bytes(binary)
            digest = hashlib.sha256(binary).hexdigest()
            backend.manifest = {"firewall": digest}
            (state / metadata).write_text(json.dumps([{"SID": backend.sid}]))
            marker = {"Schema": 1, "Service": name, "Hash": digest, "Complete": False}
            with patch.object(backend, "service_identity", return_value=True):
                self.assertFalse(backend.current("firewall"))
                (state / "managed-setup.json").write_text(json.dumps(marker))
                self.assertFalse(backend.current("firewall"))
                marker["Complete"] = True
                (state / "managed-setup.json").write_text(json.dumps(marker))
                self.assertTrue(backend.current("firewall"))
                (state / metadata).write_text(json.dumps([{"SID": "S-1-5-21-123-456-789-2222"}]))
                self.assertFalse(backend.current("firewall"))


if __name__ == "__main__":
    unittest.main()
