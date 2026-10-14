import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QPushButton
from racechat import ChatWindow
from racechat_service import Message
from racechat_store import Store

APP = QApplication.instance() or QApplication([])


class ChatUI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.window = ChatWindow(standalone=True, store=Store(self.temp.name), enable_hotkeys=False)

    def tearDown(self):
        self.window.shutdown(); self.window.close(); self.window.deleteLater()
        APP.processEvents(); self.temp.cleanup()

    def test_settings_preserve_refreshed_credentials_and_manual_token_clears_refresh(self):
        w = self.window
        w.store.update_tokens({"youtube_token": "renewed", "youtube_refresh_token": "refresh"})
        w.save_settings()
        self.assertEqual(w.store.secrets()["youtube_token"], "renewed")
        self.assertEqual(w.store.secrets()["youtube_refresh_token"], "refresh")
        w.fields["youtube_token"].setText("manual")
        w.save_settings()
        self.assertEqual(w.store.secrets()["youtube_token"], "manual")
        self.assertFalse(w.store.secrets().get("youtube_refresh_token"))

    def test_demo_never_calls_network_or_records(self):
        w = self.window
        with patch("racechat_service.request") as api:
            w.ask("hello")
            w.target.addItem('DEMO · Twitch / test', ('Twitch', 'test'))
            w.draft.setPlainText("test"); w.send_draft()
            w.read_messages(); w.toggle_recording()
            api.assert_not_called()
        self.assertIsNone(w.recording)
        self.assertEqual(w.feed.count(), 3)
        self.assertTrue(all(message.demo for message in w.messages))
        self.assertTrue(all(w.feed.item(i).text().startswith('DEMO · ') for i in range(w.feed.count())))

    def test_controls_are_in_english_and_startup_has_no_sample_messages(self):
        w = self.window
        self.assertEqual(w.windowTitle(), "RaceChat · controls and settings")
        self.assertTrue(w.banner.text().startswith("DISCONNECTED"))
        button_texts = {button.text() for button in w.findChildren(QPushButton)}
        self.assertIn("Connect configured accounts", button_texts)
        self.assertIn("Send reply · Ctrl+Alt+F11", button_texts)
        self.assertIn("Save locally (disconnects active accounts)", button_texts)
        self.assertIn("Disconnect", button_texts)
        self.assertEqual(w.feed.count(), 0)
        self.assertEqual(w.target.count(), 0)
        self.assertEqual(list(w.messages), [])
        self.assertEqual(list(w.panel.messages), [])
        with patch('racechat_service.request') as api, patch('racechat.ChatService.start') as start:
            w.start_demo(); w.tick()
            api.assert_not_called()
            start.assert_not_called()
        self.assertEqual(w.feed.count(), 0)

    def test_selected_message_routes_reply_to_its_platform(self):
        w = self.window
        w.target.addItem('Discord / 12345', ('Discord', '12345'))
        w.target.addItem('Twitch / live', ('Twitch', 'live'))
        w.add_message(Message('Twitch', 'live', 'Viewer', 'Test received message', 'received'))
        w.feed.setCurrentRow(0)
        self.assertEqual(w.target.currentData(), ("Twitch", "live"))
        self.assertIn("Viewer", w.reply_label.text())

    def test_panel_labels_each_simulated_message_and_keeps_real_heading(self):
        from PyQt6.QtGui import QImage
        w = self.window
        simulated = Message('Twitch', 'test', 'Simulated viewer', 'Example', 'demo', True)
        real = Message('Discord', '12345', 'Viewer', 'Received text', 'real')
        w.add_message(simulated)
        w.add_message(real)
        with patch('racechat.QPainter') as painter:
            image = QImage(w.panel.size(), QImage.Format.Format_ARGB32)
            w.panel.render(image)
        drawn = [call.args[-1] for call in painter.return_value.drawText.call_args_list]
        self.assertIn('DEMO · ' + simulated.heading, drawn)
        self.assertIn(real.heading, drawn)
        self.assertIn('RaceChat', drawn)
        self.assertEqual(w.panel.caption, 'RaceChat')

    def test_disconnect_and_mocked_reconnect_keep_real_history_and_remove_simulations(self):
        w = self.window
        real = Message('Twitch', 'live', 'Viewer', 'Received text', 'real')
        simulated = Message('AI', 'private', 'Simulated AI', 'Example', 'demo', True)
        w.demo = False
        w.add_message(real)
        w.add_message(simulated)
        old = w.service
        old.emit('message', Message('Twitch', 'live', 'Old service', 'Stale event', 'old'))
        with patch('racechat_service.request') as api:
            w.start_demo(); w.tick()
            self.assertTrue(old.stop_event.is_set())
            self.assertTrue(w.demo)
            self.assertEqual(list(w.messages), [real])
            self.assertEqual(list(w.panel.messages), [real])
            self.assertEqual(w.feed.count(), 1)
            self.assertEqual(w.target.count(), 0)
            with patch('racechat.ChatService.start') as start:
                w.connect_live(); w.tick()
                start.assert_called_once()
            api.assert_not_called()
        self.assertFalse(w.demo)
        self.assertEqual(list(w.messages), [real])
        self.assertEqual(w.feed.count(), 1)
        self.assertEqual(w.panel.caption, 'RaceChat')

    def test_panel_allows_drag_without_accepting_keyboard_focus(self):
        flags = self.window.panel.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertFalse(flags & Qt.WindowType.WindowTransparentForInput)

    def test_panel_caption_is_only_racechat_in_demo_and_live_states(self):
        w = self.window
        self.assertEqual(w.panel.caption, "RaceChat")
        w.demo = False
        w.recording = True
        try:
            w.tick()
            self.assertEqual(w.panel.caption, "RaceChat")
            self.assertTrue(w.recording)
        finally:
            w.recording = None

    def test_dragged_position_is_saved_without_losing_tokens(self):
        w = self.window
        w.store.update_tokens({"discord_token": "preserve"})
        area = APP.primaryScreen().availableGeometry()
        w.panel.move(area.x() + 120, area.y() + 150)
        w.panel.position_saved.emit()
        stored = w.store.load()
        self.assertEqual((stored["x"], stored["y"]), (120, 150))
        self.assertEqual(w.store.secrets()["discord_token"], "preserve")
        w.panel.move(0, 0)
        w.position_panel()
        self.assertEqual(w.panel.pos().x(), area.x() + 120)
        self.assertEqual(w.panel.pos().y(), area.y() + 150)

    def test_reset_discards_old_async_results_and_clears_draft(self):
        w = self.window
        old = w.service
        old.emit("answer", "stale answer")
        w.draft.setPlainText("old")
        w.start_demo(); w.tick()
        self.assertTrue(old.stop_event.is_set())
        self.assertEqual(w.feed.count(), 0)
        self.assertEqual(w.draft.toPlainText(), "")

    def test_send_ack_does_not_erase_new_draft(self):
        w = self.window
        w.draft.setPlainText("new draft")
        w.service.emit("sent", ("sent", "previous draft")); w.tick()
        self.assertEqual(w.draft.toPlainText(), "new draft")


if __name__ == "__main__":
    unittest.main()
