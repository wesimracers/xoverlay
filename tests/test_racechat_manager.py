import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
import unittest
from unittest.mock import patch, MagicMock
from PyQt6.QtWidgets import QApplication
import manager
APP = QApplication.instance() or QApplication([])

class RaceChatManagerTests(unittest.TestCase):
    def test_row_controls_and_bulk_toggle(self):
        with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"), patch("racechat.ChatWindow") as factory:
            chat = factory.return_value
            win = manager.ManagerWindow({}, {})
            try:
                rows = win.centralWidget()._rows
                row = next(r for r in rows if r._meta["key"] == "racechat")
                self.assertEqual(row._meta["label"], "RaceChat")
                self.assertEqual(row._btn_cfg.text(), "Config")
                self.assertEqual(row._btn_toggle.text(), "OFF")
                factory.assert_not_called()
                row._open_config()
                chat.show.assert_called_once()
                chat.connect_live.assert_not_called()
                row._toggle()
                self.assertEqual(row._btn_toggle.text(), "ON")
                chat.connect_live.assert_called_once()
                win.centralWidget()._disable_all()
                self.assertFalse(chat.manager_enabled)
                chat.panel.hide.assert_called()
                win.centralWidget()._enable_all()
                self.assertTrue(chat.manager_enabled)
                self.assertEqual(chat.connect_live.call_count, 2)
                self.assertFalse(win.menuBar().actions())
            finally:
                win.close(); win.deleteLater(); APP.processEvents()

if __name__ == "__main__":
    unittest.main()
