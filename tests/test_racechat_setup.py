"""Temporary setup boundary: local secret entry must not become a cross-site write API."""
import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request


@unittest.skipUnless(os.name == "nt", "Windows DPAPI")
class BrowserSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        path = Path(__file__).resolve().parents[1] / "tools/racechat_setup_browser.py"
        spec = importlib.util.spec_from_file_location("racechat_setup_test", path)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(os.environ, {"LOCALAPPDATA": self.temp.name}):
            spec.loader.exec_module(self.module)
        self.server = self.module.LoopbackServer(("127.0.0.1", 0), self.module.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.url = self.origin + "/" + self.module.session
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)
        self.temp.cleanup()

    def post(self, origin, csrf):
        data = urllib.parse.urlencode({"action": "save", "csrf": csrf, "discord_token": "test-token-not-real"}).encode()
        return self.http.open(urllib.request.Request(self.url, data=data, headers={"Origin": origin}), timeout=3)

    def test_cross_site_and_wrong_csrf_cannot_store_credentials(self):
        for origin, csrf in (("https://attacker.invalid", self.module.session), (self.origin, "wrong")):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(origin, csrf)
            self.assertEqual(caught.exception.code, 403)
        self.assertFalse(self.module.store.path.exists())

    def test_same_origin_saves_dpapi_without_echoing_secret(self):
        with self.post(self.origin, self.module.session) as response:
            page = response.read()
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn(b"test-token-not-real", page)
        self.assertEqual(self.module.store.secrets()["discord_token"], "test-token-not-real")
        self.assertNotIn(b"test-token-not-real", (self.module.store.path / "secrets.dpapi").read_bytes())

    def test_wrong_session_path_is_not_exposed(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.http.open(self.origin + "/wrong", timeout=3)
        self.assertEqual(caught.exception.code, 404)
