"""Race chat control window + passive overlay. Can also run without iRacing."""
import ctypes
from ctypes import wintypes
from collections import deque
import io
import json
from pathlib import Path
import queue
import sys
import wave

from PyQt6.QtCore import Qt, QTimer, QBuffer, QByteArray, QIODevice, QAbstractNativeEventFilter, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QDesktopServices
from PyQt6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QLineEdit, QComboBox, QSpinBox, QCheckBox,
    QListWidget, QListWidgetItem, QPlainTextEdit, QTabWidget, QFileDialog, QScrollArea)
from PyQt6.QtMultimedia import QAudioSource, QAudioFormat, QMediaDevices, QMediaPlayer, QAudioOutput, QAudio

from racechat_store import Store, DEFAULTS, SECRET_NAMES
from racechat_service import ChatService, Message, ServiceError


class PassivePanel(QWidget):
    position_saved = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.messages = deque(maxlen=10)
        self.caption = "RaceChat"
        self.setWindowOpacity(.92)
        self._drag = None

    def mousePressEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.position_saved.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#10151e"))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.setPen(QColor("#86e1ba"))
        p.drawText(self.rect().adjusted(14, 10, -12, -10), Qt.TextFlag.TextWordWrap, self.caption)
        y = 65
        for m in list(self.messages)[-6:]:
            color = {"Discord": "#a8acff", "Twitch": "#cd9cff", "YouTube": "#ff9292", "AI": "#86e1ba"}.get(m.platform, "#ccd5e5")
            p.setPen(QColor(color))
            p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            heading = f"{'DEMO · ' if m.demo else ''}{m.heading}"
            p.drawText(14, y, heading[:95])
            p.setPen(QColor("#edf1f8"))
            p.setFont(QFont("Segoe UI", 10))
            rect = self.rect().adjusted(14, y + 5, -14, 0)
            rect.setHeight(43)
            p.drawText(rect, Qt.TextFlag.TextWordWrap, m.text[:200])
            y += 68
            if y + 55 > self.height():
                break


class Hotkeys(QAbstractNativeEventFilter):
    """Separate IDs/keys; never intercept the existing telemetry hotkeys."""
    def __init__(self, owner):
        super().__init__()
        self.owner, self.ids = owner, []
        if sys.platform == "win32":
            for ident, key in ((0x6C91, 0x78), (0x6C92, 0x79), (0x6C93, 0x7A)):
                if ctypes.windll.user32.RegisterHotKey(None, ident, 0x4003, key):
                    self.ids.append(ident)
            QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0312 and msg.wParam in self.ids:
                fn = {0x6C91: self.owner.toggle_recording, 0x6C92: self.owner.read_messages, 0x6C93: self.owner.send_draft}[msg.wParam]
                QTimer.singleShot(0, fn)
                return True, 0
        return False, 0

    def close(self):
        QApplication.instance().removeNativeEventFilter(self)
        for ident in self.ids:
            ctypes.windll.user32.UnregisterHotKey(None, ident)
        self.ids.clear()


class ChatWindow(QDialog):
    def __init__(self, parent=None, standalone=False, store=None, enable_hotkeys=True):
        super().__init__(parent)
        self.standalone = standalone
        self.manager_enabled = True
        self.store = store or Store()
        self.load_error = ""
        try:
            self.config, self.secrets = self.store.load(), self.store.secrets()
        except Exception:
            self.config, self.secrets = dict(DEFAULTS), {}
            self.load_error = "Local settings are unreadable. Repair or restore them before saving."
        self.service = ChatService(self.config, self.secrets, persist_tokens=self.store.update_tokens)
        self.demo = True
        self.recording = None
        self.capture_buffer = None
        self.busy = False
        self.oauth_busy = False
        self.sending = False
        self.record_timer = QTimer(self)
        self.record_timer.setSingleShot(True)
        self.record_timer.timeout.connect(self.toggle_recording)
        self.panel = PassivePanel()
        self.panel.position_saved.connect(self.save_panel_position)
        self.messages = deque(maxlen=300)
        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)
        self.play_buffer = None
        self.setWindowTitle("RaceChat · controls and settings")
        self.resize(740, 760)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("QWidget { background:#171c25; color:#edf1f8; } QLabel { color:#edf1f8; } "
                           "QLineEdit,QPlainTextEdit,QListWidget,QComboBox,QSpinBox { background:#252d3a; color:#edf1f8; } "
                           "QPushButton { padding:7px; background:#344258; border:1px solid #52617a; border-radius:4px; } "
                           "QPushButton:disabled { color:#8190a7; } QCheckBox { color:#edf1f8; }")
        layout = QVBoxLayout(self)
        self.banner = QLabel("DISCONNECTED — no posts or API calls; AI replies are simulated")
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        chat = QWidget(); c = QVBoxLayout(chat)
        tabs.addTab(chat, "Chat")
        row = QHBoxLayout(); c.addLayout(row)
        self.connect_button = QPushButton("Connect configured accounts")
        self.connect_button.clicked.connect(self.connect_live); row.addWidget(self.connect_button)
        button = QPushButton("Disconnect")
        button.clicked.connect(self.start_demo); row.addWidget(button)
        self.preview = QCheckBox("Show panel outside iRacing")
        self.preview.setChecked(standalone); c.addWidget(self.preview)
        self.feed = QListWidget(); self.feed.setWordWrap(True)
        self.feed.currentItemChanged.connect(self.select_message); c.addWidget(self.feed, 1)
        self.target = QComboBox(); c.addWidget(self.target)
        self.reply_label = QLabel("Destination and reply: select a message or channel")
        self.reply_label.setWordWrap(True); c.addWidget(self.reply_label)
        self.target.currentIndexChanged.connect(self.update_reply_label)
        self.draft = QPlainTextEdit(); self.draft.setPlaceholderText("Reply to post — check the destination before sending")
        self.draft.setMaximumHeight(80); c.addWidget(self.draft)
        self.send_button = QPushButton("Send reply · Ctrl+Alt+F11")
        self.send_button.clicked.connect(self.send_draft); c.addWidget(self.send_button)
        self.prompt = QLineEdit(); self.prompt.setPlaceholderText("Chat with AI (does not post to chat)")
        self.prompt.returnPressed.connect(self.ask); c.addWidget(self.prompt)
        row = QHBoxLayout(); c.addLayout(row)
        button = QPushButton("Ask AI"); button.clicked.connect(self.ask); row.addWidget(button)
        button = QPushButton("Read messages · Ctrl+Alt+F10"); button.clicked.connect(self.read_messages); row.addWidget(button)
        button = QPushButton("Stop audio"); button.clicked.connect(self.player.stop); row.addWidget(button)
        self.include_chat = QCheckBox("Include the last 12 messages when asking AI (sent to OpenAI)")
        c.addWidget(self.include_chat)
        self.speak_answer = QCheckBox("Read AI replies aloud — synthetic voice")
        self.speak_answer.setChecked(True); c.addWidget(self.speak_answer)
        self.mic_consent = QCheckBox("Enable my microphone on command; audio is sent to OpenAI")
        self.mic_consent.toggled.connect(self.microphone_consent_changed); c.addWidget(self.mic_consent)
        self.devices = QComboBox()
        for device in QMediaDevices.audioInputs():
            self.devices.addItem(device.description(), device)
        c.addWidget(self.devices)
        self.mic_mode = QComboBox(); self.mic_mode.addItems(["Talk to AI", "Dictate a reply to the selected destination"])
        c.addWidget(self.mic_mode)
        self.mic_button = QPushButton("Record / stop · Ctrl+Alt+F9 · 30 s max")
        self.mic_button.clicked.connect(self.toggle_recording); c.addWidget(self.mic_button)
        settings = QWidget(); form = QFormLayout(settings)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(settings)
        tabs.addTab(scroll, "Local settings")
        self.fields = {}
        labels = {"discord_guild": "Discord · server ID (all accessible channels)", "discord_channels": "Discord · channel IDs (comma separated)", "twitch_client_id": "Twitch · Client ID",
                  "twitch_channel": "Twitch · channel login", "youtube_video": "YouTube · live video ID (11 characters)",
                  "model": "OpenAI · chat model", "transcribe_model": "Transcription model", "speech_model": "Speech model", "voice": "Voice"}
        for key, label in labels.items():
            field = QLineEdit(str(self.config[key])); self.fields[key] = field; form.addRow(label, field)
        for key, label in zip(SECRET_NAMES, ("Discord · bot token", "Twitch · User Access Token OAuth", "YouTube · Access Token OAuth", "OpenAI · API key")):
            field = QLineEdit(); field.setEchoMode(QLineEdit.EchoMode.Password)
            field.setPlaceholderText("Saved; leave blank to keep" if self.secrets.get(key) else "Enter only here, on this computer")
            self.fields[key] = field; form.addRow(label, field)
        button = QPushButton("Authorize Twitch in browser (public app)")
        button.clicked.connect(lambda: self.authorize("Twitch")); form.addRow(button)
        button = QPushButton("Authorize YouTube — import Google Desktop JSON")
        button.clicked.connect(lambda: self.authorize("YouTube")); form.addRow(button)
        button = QPushButton("Cancel authorization")
        button.clicked.connect(self.start_demo); form.addRow(button)
        self.screen = QComboBox()
        for i, screen in enumerate(QApplication.screens()):
            self.screen.addItem(f"{i + 1}: {screen.name()}", i)
        self.screen.setCurrentIndex(min(int(self.config["screen"]), self.screen.count() - 1))
        form.addRow("Panel monitor", self.screen)
        for key, label, lo, hi in (("x", "X position on monitor", 0, 10000), ("y", "Y position on monitor", 0, 10000),
                                  ("width", "Width", 320, 1400), ("height", "Height", 220, 1600)):
            field = QSpinBox(); field.setRange(lo, hi); field.setValue(int(self.config[key]))
            self.fields[key] = field; form.addRow(label, field)
        button = QPushButton("Save locally (disconnects active accounts)")
        button.clicked.connect(self.save_settings); form.addRow(button)
        button = QPushButton("Delete saved credentials")
        button.clicked.connect(self.clear_credentials); form.addRow(button)
        note = QLabel("Secrets: Windows user DPAPI, outside the project.\n"
            "AI: uses your own API account and billing; it does not use your Codex subscription.\n"
            "Discord voice: awaiting DAVE integration. Does not join, listen to, or record channels.\n"
            "No screen or webcam capture, video streaming, or automatic replies.\n"
            "OAuth: buttons open the browser only when requested; tokens refresh when the platform allows it.\n"
            "Full instructions: main/RACE_CHAT.md")
        note.setWordWrap(True); form.addRow(note)
        self.status = QLabel(self.load_error or "Ready. Configure accounts to use live connections.")
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.statuses = {}
        self.hotkeys = Hotkeys(self) if enable_hotkeys else None
        if self.hotkeys and len(self.hotkeys.ids) != 3:
            self.status.setText("Some shortcuts are unavailable because they are already in use. The buttons still work.")
        self.timer = QTimer(self); self.timer.timeout.connect(self.tick); self.timer.start(100)
        self.start_demo()
        self.position_panel()

    def save_panel_position(self):
        screens = QApplication.screens()
        selected = QApplication.screenAt(self.panel.frameGeometry().center()) or self.panel.screen()
        index = screens.index(selected) if selected in screens else 0
        area = screens[index].availableGeometry()
        changes = {"screen": index, "x": self.panel.x() - area.x(), "y": self.panel.y() - area.y()}
        try:
            self.store.update_settings(changes)
            self.config.update(changes)
            self.screen.setCurrentIndex(index)
            for key in ("x", "y"):
                self.fields[key].setValue(changes[key])
        except Exception:
            self.status.setText("Could not save the RaceChat position.")

    def position_panel(self):
        screens = QApplication.screens()
        screen = screens[max(0, min(int(self.config["screen"]), len(screens)-1))].availableGeometry()
        width, height = min(int(self.config["width"]), screen.width()), min(int(self.config["height"]), screen.height())
        x = screen.x() + max(0, min(int(self.config["x"]), screen.width()-width))
        y = screen.y() + max(0, min(int(self.config["y"]), screen.height()-height))
        self.panel.setGeometry(x, y, width, height)

    def reset_service(self):
        # Keep received/local real messages in memory, but remove simulations
        # whenever connection state changes. Old service events stay discarded.
        history = [message for message in self.messages if not message.demo]
        self.cancel_recording()
        self.player.stop()
        self.service.stop()
        self.service = ChatService(self.config, self.secrets, persist_tokens=self.store.update_tokens)
        self.busy = self.sending = False
        self.oauth_busy = False
        self.feed.clear(); self.target.clear(); self.messages.clear(); self.panel.messages.clear()
        self.draft.clear(); self.statuses.clear()
        for message in history:
            self.add_message(message)
        self.panel.update()

    def start_demo(self):
        """Disconnect without sample messages; retain the manager's legacy entry point."""
        self.reset_service(); self.demo = True
        self.banner.setText("DISCONNECTED — no posts or API calls; AI replies are simulated")
        self.connect_button.setEnabled(True)

    def save_settings(self):
        with self.service.token_lock:
            self._save_settings()

    def _save_settings(self):
        try:
            config = dict(self.config)
            secrets = self.store.secrets()
            for key, field in self.fields.items():
                if key in SECRET_NAMES:
                    if field.text().strip():
                        secrets[key] = field.text().strip()
                        if key in ("twitch_token", "youtube_token"):
                            secrets.pop(key.replace("_token", "_refresh_token"), None)
                else:
                    config[key] = field.value() if isinstance(field, QSpinBox) else field.text().strip()
            config["screen"] = max(0, self.screen.currentIndex())
            self.store.save(config, secrets)
            self.config, self.secrets = config, secrets
            for key in SECRET_NAMES:
                self.fields[key].clear()
                self.fields[key].setPlaceholderText("Saved; leave blank to keep" if secrets.get(key) else "Enter only here")
            self.start_demo(); self.position_panel()
            self.status.setText("Settings saved. Click Connect configured accounts to start.")
        except Exception:
            self.status.setText("Could not save settings or DPAPI secrets. Nothing was connected.")

    def clear_credentials(self):
        with self.service.token_lock:
            self._clear_credentials()

    def _clear_credentials(self):
        try:
            self.store.save(self.config, {})
            self.secrets = {}
            for key in SECRET_NAMES:
                self.fields[key].clear(); self.fields[key].setPlaceholderText("No credential")
            self.start_demo(); self.status.setText("Local credentials deleted. Revoke platform tokens if needed.")
        except Exception:
            self.status.setText("Could not delete local credentials.")

    def authorize(self, platform):
        if self.oauth_busy:
            self.status.setText("An authorization is already pending. Finish or cancel it."); return
        from racechat_oauth import twitch_device, google_desktop
        client = None
        if platform == "YouTube":
            try:
                if self.secrets.get("google_client_json"):
                    client = json.loads(self.secrets["google_client_json"])
                else:
                    path, _ = QFileDialog.getOpenFileName(self, "Google OAuth JSON — Desktop app", "", "JSON (*.json)")
                    if not path:
                        return
                    client = json.loads(Path(path).read_text(encoding="utf-8"))["installed"]
            except Exception:
                self.status.setText("Invalid JSON: a Google Desktop client (installed) is required."); return
        elif not self.config["twitch_client_id"]:
            self.status.setText("Enter and SAVE the Twitch Client ID before authorizing."); return
        self.start_demo()
        self.oauth_busy = True
        service = self.service
        def work():
            try:
                tokens = (twitch_device(self.config["twitch_client_id"], service.emit, service.stop_event)
                          if platform == "Twitch" else google_desktop(client, service.emit, service.stop_event))
                if platform == "YouTube":
                    tokens["google_client_json"] = json.dumps({k: client[k] for k in ("client_id", "client_secret")})
                service.emit("oauth_tokens", tokens)
            finally:
                service.emit("oauth_done", None)
        service.launch(work)
        self.status.setText("Starting authorization. Chat connections are disconnected.")

    def connect_live(self):
        try:
            with self.service.token_lock:
                self.service.stop()
                self.config, self.secrets = self.store.load(), self.store.secrets()
                if self.store.sync_status.get('migration_pending'):
                    self.status.setText('RaceChat synchronization is ready. Open this overlay in the configured peer Windows account once to migrate its existing credentials.')
                    return
                self.reset_service()
            self.demo = False
            self.service.start()
            self.banner.setText("LIVE SESSION · posts only on command · microphone off")
            self.connect_button.setEnabled(False)
            self.status.setText("Connecting configured destinations. OpenAI is available if an API key is configured.")
        except (ServiceError, RuntimeError, OSError, ValueError) as exc:
            self.status.setText(str(exc))

    def add_message(self, m):
        self.messages.append(m); self.panel.messages.append(m); self.panel.update()
        item = QListWidgetItem(f"{'DEMO · ' if m.demo else ''}{m.heading}\n{m.text}")
        item.setData(Qt.ItemDataRole.UserRole, m); self.feed.addItem(item)
        while self.feed.count() > 300:
            self.feed.takeItem(0)
        self.feed.scrollToBottom()

    def selected(self):
        item = self.feed.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def target_index(self, destination):
        return next((i for i in range(self.target.count()) if self.target.itemData(i) == destination), -1)

    def select_message(self, current, previous):
        m = self.selected()
        if m:
            i = self.target_index((m.platform, m.channel))
            if i >= 0:
                self.target.setCurrentIndex(i)
        self.update_reply_label()

    def update_reply_label(self):
        m, destination = self.selected(), self.target.currentData()
        replying = m and (m.platform, m.channel) == destination
        self.reply_label.setText(f"Destination: {self.target.currentText()}" + (f" · reply to {m.author}" if replying else " · channel message"))

    def send_draft(self):
        if self.sending:
            return
        text, dest, reply = self.draft.toPlainText().strip(), self.target.currentData(), self.selected()
        if not text or not dest:
            self.status.setText("Select a destination and type or dictate a reply."); return
        if self.demo:
            self.add_message(Message(dest[0], dest[1], "You (simulated post)", text, "demo-send", True))
            self.draft.clear(); self.status.setText("Simulated post — nothing was published."); return
        self.sending = True
        service = self.service
        def work():
            try:
                service.send(dest, text, reply)
            finally:
                service.emit("send_done", text)
        service.launch(work)
        self.status.setText("Sending. If the outcome is unclear, check the channel before retrying.")

    def ask(self, prompt=None):
        prompt = prompt if isinstance(prompt, str) else self.prompt.text().strip()
        if not prompt or self.busy:
            return
        self.prompt.clear()
        self.add_message(Message("You", "private", "You", prompt, "local", self.demo))
        if self.demo:
            self.add_message(Message("AI", "private", "Simulated AI", "Demo: I can chat, read messages, and draft replies. Connect the API to chat live.", "demo-ai", True)); return
        self.busy = True
        service, context, speak = self.service, list(self.messages) if self.include_chat.isChecked() else [], self.speak_answer.isChecked()
        def work():
            try:
                answer = service.ask(prompt, context)
                service.emit("answer", answer)
                if speak:
                    service.emit("audio", service.speech(answer))
            finally:
                service.emit("done", None)
        service.launch(work)

    def read_messages(self):
        if self.busy:
            return
        selected = self.selected()
        messages = [selected] if selected else list(self.messages)[-5:]
        text = ". ".join(f"{m.platform}, {m.author}: {m.text}" for m in messages)
        if self.demo:
            self.status.setText("DEMO: simulated reading. " + text[:220]); return
        self.busy = True
        service = self.service
        def work():
            try:
                service.emit("audio", service.speech(text))
            finally:
                service.emit("done", None)
        service.launch(work)

    def microphone_consent_changed(self, enabled):
        if not enabled:
            self.cancel_recording()

    def cancel_recording(self):
        self.record_timer.stop()
        if self.recording:
            self.recording.stop(); self.recording.deleteLater(); self.recording = None
        self.mic_button.setText("Record / stop · Ctrl+Alt+F9 · 30 s max")

    def toggle_recording(self):
        if self.recording:
            self.cancel_recording()
            pcm = bytes(self.capture_buffer.data())
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000); wav.writeframes(pcm)
            self.capture_buffer.close(); self.capture_buffer.deleteLater(); self.capture_buffer = None
            if len(pcm) < 4800:
                self.status.setText("Recording is empty or too short. Check the microphone."); return
            service, mode, dest = self.service, self.record_mode, self.record_destination
            self.busy = True
            def work():
                try:
                    text = service.transcribe(output.getvalue())
                    service.emit("transcript", (mode, dest, text))
                finally:
                    service.emit("done", None)
            service.launch(work)
            self.status.setText("Microphone off. Transcribing…")
            return
        if self.demo or not self.mic_consent.isChecked() or not self.secrets.get("openai_key"):
            self.status.setText("To record: configure OpenAI, start a live session, and enable microphone consent."); return
        if self.busy:
            self.status.setText("Wait for the current voice or AI operation."); return
        device = self.devices.currentData()
        if device is None:
            self.status.setText("No input device available."); return
        fmt = QAudioFormat(); fmt.setSampleRate(24000); fmt.setChannelCount(1); fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(fmt):
            self.status.setText("Microphone does not support 24 kHz, 16 bit mono PCM. Choose another device."); return
        self.player.stop()
        if self.capture_buffer:
            self.capture_buffer.close(); self.capture_buffer.deleteLater()
        self.capture_buffer = QBuffer(self); self.capture_buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        self.record_mode, self.record_destination = self.mic_mode.currentIndex(), self.target.currentData()
        self.recording = QAudioSource(device, fmt, self)
        self.recording.start(self.capture_buffer)
        if self.recording.error() != QAudio.Error.NoError:
            self.cancel_recording()
            self.status.setText("Could not open the selected microphone."); return
        self.record_timer.start(30000)
        self.mic_button.setText("● RECORDING MICROPHONE — click or press Ctrl+Alt+F9 to stop")
        self.status.setText("Selected microphone is active. Discord channel audio is not captured.")

    def tick(self):
        for _ in range(80):
            try:
                kind, value = self.service.events.get_nowait()
            except queue.Empty:
                break
            if kind == "message":
                self.add_message(value)
            elif kind == "destination":
                if self.target_index(value) < 0:
                    self.target.addItem(f"{value[0]} / {value[1]}", value)
            elif kind == "answer":
                self.add_message(Message("AI", "private", "AI", value, "answer"))
            elif kind == "audio":
                self.player.stop()
                self.player.setSourceDevice(None)
                if self.play_buffer:
                    self.play_buffer.deleteLater()
                self.play_buffer = QBuffer(self)
                self.play_buffer.setData(QByteArray(value)); self.play_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
                self.player.setSourceDevice(self.play_buffer); self.player.play()
            elif kind == "transcript":
                mode, dest, text = value
                if mode == 1:
                    index = self.target_index(dest)
                    if index >= 0:
                        self.target.setCurrentIndex(index)
                    self.draft.setPlainText(text)
                    self.status.setText("Dictation ready. Check destination and text; Ctrl+Alt+F11 posts.")
                else:
                    self.busy = False
                    command = text.strip().lower().rstrip(".!?")
                    if command in ("read messages", "ler mensagens", "leia as mensagens"):
                        QTimer.singleShot(0, self.read_messages)
                    elif command in ("send reply", "enviar resposta"):
                        QTimer.singleShot(0, self.send_draft)
                    else:
                        QTimer.singleShot(0, lambda t=text: self.ask(t))
            elif kind == "done":
                self.busy = False
            elif kind == "send_done":
                self.sending = False
            elif kind == "oauth_browser":
                QDesktopServices.openUrl(QUrl(value))
            elif kind == "tokens_refreshed":
                self.secrets.update(value)
            elif kind == "oauth_tokens":
                try:
                    secrets = self.store.update_tokens(value)
                    self.secrets = secrets
                    for key in value:
                        if key in self.fields:
                            self.fields[key].clear(); self.fields[key].setPlaceholderText("Saved via OAuth")
                    self.status.setText("Authorized and saved with DPAPI. Click Connect configured accounts.")
                except Exception:
                    self.status.setText("Could not save OAuth credentials; repair DPAPI and authorize again.")
            elif kind == "oauth_done":
                self.oauth_busy = False
            elif kind == "sent":
                status, sent_text = value
                if self.draft.toPlainText().strip() == sent_text:
                    self.draft.clear()
                self.status.setText(status)
            else:
                self.status.setText(str(value))
        self.send_button.setEnabled(not self.sending)
        self.panel.caption = "RaceChat"
        self.panel.update()
        visible = self.preview.isChecked()
        if not visible and not self.standalone:
            import core
            visible = bool(getattr(core.ir, "is_connected", False) and core.sg("IsOnTrack", False) and not core.sg("IsReplayPlaying", False))
        visible = visible and self.manager_enabled
        if self.panel.isVisible() != visible:
            self.panel.setVisible(visible)

    def shutdown(self):
        self.cancel_recording(); self.player.stop(); self.service.stop()
        if self.hotkeys:
            self.hotkeys.close(); self.hotkeys = None
        self.timer.stop(); self.panel.close()

    def reject(self):
        self.cancel_recording()
        if self.standalone:
            self.close()
        else:
            super().reject()

    def closeEvent(self, event):
        self.cancel_recording()
        if self.standalone:
            self.shutdown()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChatWindow(standalone=True)
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    sys.exit(app.exec())
