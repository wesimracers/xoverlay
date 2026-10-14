"""Offscreen rendering only; no live helper, prompt or user-settings writes."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
import sys
from pathlib import Path
from unittest.mock import Mock, patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "main"))
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QRadioButton
import manager
import race_protection

app = QApplication.instance() or QApplication([])
QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\segoeui.ttf")
app.setFont(QFont("Segoe UI", 9))
manager.apply_dark_theme(app)
qa = ROOT / (sys.argv[sys.argv.index("--stage") + 1] if "--stage" in sys.argv else "build-staging-portable") / "qa"
qa.mkdir(parents=True, exist_ok=True)
with patch.object(manager.core, "cfg", {"windows": {}}), patch.object(manager.core, "save_cfg"), patch.object(race_protection, "monitors", return_value=[]):
    protection = Mock()
    protection.settings = race_protection.DEFAULTS.copy()
    protection.administrative = None
    protection.pause_file.exists.return_value = False
    protection.status.return_value = {"Mode": "active", "Windows": "active", "Routing": "active, without activating windows",
        "Toasts": "policy applied; Windows behavior needs validation", "Focus": "already configured", "Firewall": "NotifyOnListen=False confirmed",
        "UAC": "not blocked; administrative setup not confirmed", "Setup": "Simulated setup: awaiting personal Windows approval; not live evidence.", "Pending": False}
    protection.diagnostic_text.return_value = "Experimental global broker gate. Live validation remains required."
    win = manager.ManagerWindow({}, {}, protection=protection)
    dialog = manager.ProtectionConfigDialog(win)
    allowed = manager.AllowedApplicationsDialog(dialog)
    try:
        win.show(); dialog.show(); allowed.show(); app.processEvents()
        win.grab().save(str(qa / "manager-gate.png"))
        dialog.grab().save(str(qa / "general-gate.png"))
        allowed.grab().save(str(qa / "allowed-applications.png"))
        dialog._protection_inputs["block_elevation"].click(); app.processEvents()
        assert dialog._protection_inputs["block_elevation"].isChecked()
        assert not dialog._allow_mode.isChecked()
        assert dialog._allowed_button.isEnabled() and len(dialog._allowed_apps) == 9
        dialog.grab().save(str(qa / "general-block-all.png"))
        assert dialog._allow_mode.mapTo(dialog, dialog._allow_mode.rect().topLeft()).y() == dialog._protection_inputs["block_elevation"].mapTo(dialog, dialog._protection_inputs["block_elevation"].rect().topLeft()).y()
        assert dialog.height() <= 1000, "Config should fit a 1080p display"
        dialog._allow_mode.click(); app.processEvents()
        assert not dialog._protection_inputs["block_elevation"].isChecked()
        assert len(dialog._allowed_apps) == 9
        text = "\n".join(label.text() for widget in (win, dialog, allowed) for label in widget.findChildren(QLabel))
        text += "\n" + "\n".join(button.text() for widget in (win, dialog, allowed) for button in widget.findChildren(QPushButton))
        text += "\n" + "\n".join(button.text() for button in dialog.findChildren(QRadioButton))
        assert "not blocked; administrative setup not confirmed" in text
        assert "Retry administrative setup" in text
        assert "Remove administrative helpers" in text
        assert "Find installed apps" in text and "Open selected" in text
        assert "Block new interactive elevations globally (experimental)" in text
        assert "Allow" in text and "Block all" in text and "9 saved" in text
        assert "denied apps can still display errors" in text
        assert not any(word in text.lower() for word in ("proteção", "aguardando", "restauração", "solicitações"))
        (qa / "visible-ui-text.txt").write_text(text, encoding="utf-8")
        print(f"Offscreen gate UI rendered: manager={win.width()}x{win.height()}, config={dialog.width()}x{dialog.height()}")
    finally:
        allowed.close(); dialog.close(); win.close(); app.processEvents()
