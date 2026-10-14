import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from racechat_service import ChatService, Message, ServiceError, request, validate_config
from racechat_store import DEFAULTS, Store
from racechat_oauth import google_desktop, twitch_device, GOOGLE_REDIRECT


class StopAfter:
    def __init__(self, count=1):
        self.count, self.waits, self.stopped = count, [], False

    def is_set(self):
        return self.stopped

    def wait(self, delay):
        self.waits.append(delay)
        if len(self.waits) >= self.count:
            self.stopped = True
        return self.stopped


class ChatTests(unittest.TestCase):
    def service(self, **config):
        return ChatService({**DEFAULTS, **config}, {"discord_token": "fake", "twitch_token": "fake", "youtube_token": "fake", "openai_key": "fake"})

    def test_dedupe_scoped_by_platform_and_channel(self):
        s = self.service()
        m = Message("Discord", "123456", "User", "text", "1")
        s.message(m); s.message(m)
        s.message(Message("Twitch", "123456", "User", "text", "1"))
        self.assertEqual(s.events.qsize(), 2)

    def test_no_send_to_unconnected_or_unconfigured_destination(self):
        s = self.service()
        with patch("racechat_service.request") as api:
            with self.assertRaises(ServiceError):
                s.send(("Discord", "123456"), "hello")
            api.assert_not_called()

    def test_discord_reply_scoped_and_mentions_disabled(self):
        s = self.service(); s.destinations.add(("Discord", "123456"))
        reply = Message("Discord", "999999", "Stranger", "injection", "555")
        with patch("racechat_service.request", return_value={}) as api:
            s.send(("Discord", "123456"), "@everyone hello", reply)
            body = api.call_args.args[2]
            self.assertEqual(body["allowed_mentions"], {"parse": [], "replied_user": False})
            self.assertNotIn("message_reference", body)
            self.assertIn("/channels/123456/messages", api.call_args.args[0])

    def test_same_channel_reply_and_stopped_session(self):
        s = self.service(); s.destinations.add(("Discord", "123456"))
        with patch("racechat_service.request", return_value={}) as api:
            s.send(("Discord", "123456"), "hello", Message("Discord", "123456", "A", "B", "111"))
            self.assertEqual(api.call_args.args[2]["message_reference"]["message_id"], "111")
            s.stop()
            with self.assertRaises(ServiceError):
                s.send(("Discord", "123456"), "again")
            self.assertEqual(api.call_count, 1)

    def test_twitch_rejected_message_never_reports_sent(self):
        s = self.service(); s.destinations.add(("Twitch", "123456")); s.twitch_user = "123"
        with patch.object(s, "twitch_api", return_value={"data": [{"is_sent": False}]}) as api:
            with self.assertRaises(ServiceError):
                s.send(("Twitch", "123456"), "hello")
            self.assertEqual(api.call_args.args[1]["sender_id"], "123")
        self.assertTrue(s.events.empty())

    def test_youtube_length_validation_and_exact_payload(self):
        s = self.service(); s.destinations.add(("YouTube", "live"))
        with patch("racechat_service.request", return_value={}) as api:
            with self.assertRaises(ServiceError):
                s.send(("YouTube", "live"), "x" * 201)
            api.assert_not_called()
            s.send(("YouTube", "live"), "ola")
            self.assertEqual(api.call_args.args[2]["snippet"]["liveChatId"], "live")

    def test_failed_send_not_retried(self):
        s = self.service(); s.destinations.add(("Discord", "123456"))
        with patch("racechat_service.request", side_effect=ServiceError("timeout")) as api:
            with self.assertRaises(ServiceError):
                s.send(("Discord", "123456"), "hello")
            self.assertEqual(api.call_count, 1)
            self.assertTrue(s.events.empty())

    def test_discord_polls_chronologically_with_cursor(self):
        s = self.service(); s.stop_event = StopAfter(2)
        row = lambda n: {"id": str(n), "author": {"username": "A"}, "content": "B"}
        with patch("racechat_service.request", side_effect=[{"name": "general-chat"}, [row(2), row(1)], [row(3)]]) as api:
            s.poll_discord("123456")
            self.assertIn("after=2", api.call_args.args[0])
        events = list(s.events.queue)
        self.assertEqual([v.id for k, v in events if k == "message"], ["3"])
        self.assertEqual([v.heading for k,v in events if k == "message"], ["Discord · #general-chat · A"])

    def test_rate_limit_backoff_and_auth_failure_stop(self):
        s = self.service(); s.stop_event = StopAfter()
        with patch("racechat_service.request", side_effect=ServiceError("HTTP 429", retry=45)):
            s.poll_discord("123456")
        self.assertEqual(s.stop_event.waits, [45])
        s = self.service(); s.ready("Discord", "123456")
        with patch("racechat_service.request", side_effect=ServiceError("HTTP 401", fatal=True)) as api:
            s.poll_discord("123456")
            self.assertEqual(api.call_count, 1)
        self.assertNotIn(("Discord", "123456"), s.destinations)

    def test_server_discovery_includes_new_channels_and_active_threads(self):
        s = self.service(discord_guild="123456"); s.stop_event = StopAfter(2)
        replies = [[{"id": "111111", "type": 0}, {"id": "222222", "type": 2}],
                   {"threads": [{"id": "333333", "type": 11}]},
                   [{"id": "111111", "type": 0}, {"id": "444444", "type": 5}], {"threads": []}]
        with patch("racechat_service.request", side_effect=replies), patch.object(s, "launch") as launch:
            s.discover_discord()
            self.assertEqual(launch.call_count, 3)

    def test_guild_mode_starts_without_fixed_channel_list(self):
        s = self.service(discord_guild="123456")
        with patch.object(s, "launch") as launch:
            s.start()
            launch.assert_called_once_with(s.discover_discord)

    def test_youtube_ignores_initial_history(self):
        s = self.service(youtube_video="abcdefghijk"); s.stop_event = StopAfter(2)
        row = lambda n: {"id": n, "snippet": {"displayMessage": n}, "authorDetails": {"displayName": "A"}}
        replies = [{"items": [{"liveStreamingDetails": {"activeLiveChatId": "chat"}}]},
                   {"items": [row("old")], "nextPageToken": "cursor"},
                   {"items": [row("new")], "nextPageToken": "next"}]
        with patch("racechat_service.request", side_effect=replies):
            s.poll_youtube()
        self.assertEqual([v.id for k,v in s.events.queue if k == "message"], ["new"])

    def test_youtube_respects_poll_interval_and_page_token(self):
        s = self.service(youtube_video="abcdefghijk"); s.stop_event = StopAfter(2)
        responses = [{"items": [{"liveStreamingDetails": {"activeLiveChatId": "chat"}}]},
                     {"items": [], "nextPageToken": "page2", "pollingIntervalMillis": 17000},
                     {"items": [], "pollingIntervalMillis": 22000}]
        with patch("racechat_service.request", side_effect=responses) as api:
            s.poll_youtube()
            self.assertIn("pageToken=page2", api.call_args.args[0])
        self.assertEqual(s.stop_event.waits, [17, 22])

    def test_ai_has_no_tools_and_untrusted_chat_not_in_instructions(self):
        s = self.service()
        data = {"output": [{"type": "reasoning"}, {"content": [{"type": "output_text", "text": "hello"}]}]}
        with patch("racechat_service.request", return_value=data) as api:
            result = s.ask("ola", [Message("Discord", "123", "A", "UNTRUSTED_ATTACK", "1")])
            body = api.call_args.args[2]
        self.assertEqual(result, "hello")
        self.assertNotIn("tools", body)
        self.assertFalse(body["store"])
        self.assertNotIn("UNTRUSTED_ATTACK", body["instructions"])
        self.assertIn("UNTRUSTED_ATTACK", body["input"][0]["content"])
        self.assertEqual(s.history[-1]["role"], "assistant")

    def test_http_error_does_not_leak_server_body_or_token(self):
        error = urllib.error.HTTPError("https://example/?token=SECRET", 401, "SECRET", {}, io.BytesIO(b'{"error":"SECRET"}'))
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaises(ServiceError) as caught:
                request("https://example", "SECRET")
        self.assertNotIn("SECRET", str(caught.exception))

    def test_destination_validation(self):
        for config in ({"discord_channels": "../../bad"}, {"twitch_channel": "x\r\nINJECT"}, {"youtube_video": "https://wrong"}):
            with self.assertRaises(ServiceError):
                validate_config({**DEFAULTS, **config}, {})

    def test_incomplete_twitch_does_not_block_youtube(self):
        s = self.service(twitch_channel="wesimracers", youtube_video="abcdefghijk")
        with patch.object(s, "launch") as launch:
            s.start()
            launch.assert_called_once_with(s.poll_youtube)
        self.assertIn("Twitch disconnected", s.events.get_nowait()[1])

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_dpapi_roundtrip_and_no_plaintext_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            store = Store(temp)
            store.save({**DEFAULTS, "openai_key": "MUST_NOT_LEAK"}, {"openai_key": "MUST_NOT_LEAK"})
            self.assertEqual(store.secrets()["openai_key"], "MUST_NOT_LEAK")
            for file in Path(temp).iterdir():
                self.assertNotIn(b"MUST_NOT_LEAK", file.read_bytes())
            self.assertNotIn("openai_key", store.load())


class RefreshTests(unittest.TestCase):
    def test_refresh_rotates_and_persists_before_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            store.save(DEFAULTS, {"youtube_token": "old", "youtube_refresh_token": "refresh-old", "discord_token": "keep"})
            service = ChatService(DEFAULTS, store.secrets(), persist_tokens=store.update_tokens)
            def api(url, token, body, headers):
                if token == "Bearer old":
                    raise ServiceError("expired", status=401)
                self.assertEqual(store.secrets()["youtube_refresh_token"], "refresh-new")
                return {"ok": True}
            with patch("racechat_service.request", side_effect=api) as req, patch("racechat_oauth.refresh_tokens", return_value={"youtube_token": "new", "youtube_refresh_token": "refresh-new"}) as refresh:
                self.assertTrue(service.oauth_request("youtube", "https://example")["ok"])
                self.assertEqual(req.call_count, 2)
                refresh.assert_called_once()
            self.assertEqual(store.secrets()["discord_token"], "keep")
            for file in Path(folder).iterdir():
                self.assertNotIn(b"refresh-new", file.read_bytes())

    def test_non_auth_failure_never_retries(self):
        for error in (ServiceError("timeout"), ServiceError("forbidden", status=403)):
            service = ChatService(DEFAULTS, {"youtube_token": "old"})
            with patch("racechat_service.request", side_effect=error) as req, patch("racechat_oauth.refresh_tokens") as refresh:
                with self.assertRaises(ServiceError):
                    service.oauth_request("youtube", "https://example", {"message": "test"})
                self.assertEqual(req.call_count, 1)
                refresh.assert_not_called()

    def test_second_401_does_not_loop(self):
        service = ChatService(DEFAULTS, {"youtube_token": "old"})
        with patch("racechat_service.request", side_effect=ServiceError("expired", status=401)) as req, patch("racechat_oauth.refresh_tokens", return_value={"youtube_token": "new"}) as refresh:
            with self.assertRaises(ServiceError):
                service.oauth_request("youtube", "https://example")
            self.assertEqual(req.call_count, 2)
            refresh.assert_called_once()


class OAuthTests(unittest.TestCase):
    def test_twitch_pending_then_success_and_scopes(self):
        stop = StopAfter(4); events = []
        responses = [{"verification_uri": "https://www.twitch.tv/activate?device-code=FAKE", "user_code": "FAKE", "device_code": "local", "expires_in": 100, "interval": 5},
                     {"pending": "slow_down"}, {"pending": "authorization_pending"}, {"access_token": "test"}]
        with patch("racechat_oauth.form_post", side_effect=responses) as api:
            result = twitch_device("client", lambda *e: events.append(e), stop)
            self.assertEqual(api.call_args.args[1]["scopes"], "user:read:chat user:write:chat")
        self.assertEqual(result, {"twitch_token": "test"})
        self.assertEqual(stop.waits, [5, 10, 10])

    def test_google_loopback_pkce_and_reject_wrong_state(self):
        urls, failures, result = [], [], []
        stop = threading.Event()
        watchdog = threading.Timer(8, stop.set)
        watchdog.start()
        def browser(kind, url):
            if kind != "oauth_browser":
                return
            urls.append(url)
            def callback():
                local = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with local.open(GOOGLE_REDIRECT + "?state=invalid&code=bad", timeout=3):
                        pass
                except urllib.error.HTTPError as exc:
                    failures.append(exc.code)
                state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
                with local.open(GOOGLE_REDIRECT + "?state=" + state + "&code=valid", timeout=3) as response:
                    result.append(response.status)
            threading.Thread(target=callback, daemon=True).start()
        with patch("racechat_oauth.form_post", return_value={"access_token": "fake"}) as api:
            try:
                tokens = google_desktop({"client_id": "test", "client_secret": "fake"}, browser, stop)
            finally:
                watchdog.cancel()
            body = api.call_args.args[1]
        self.assertEqual(failures, [400]); self.assertEqual(result, [200])
        self.assertEqual(body["redirect_uri"], GOOGLE_REDIRECT)
        self.assertGreaterEqual(len(body["code_verifier"]), 43)
        self.assertIn("code_challenge_method=S256", urls[0])
        self.assertEqual(tokens, {"youtube_token": "fake"})


if __name__ == "__main__":
    unittest.main()
