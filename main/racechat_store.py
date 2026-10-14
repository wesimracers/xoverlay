"""Local chat preferences and Windows user-scoped DPAPI secrets (no telemetry config)."""
import ctypes
from ctypes import wintypes
import json
import os
import threading
from pathlib import Path

DEFAULTS = {
    "discord_channels": "", "discord_guild": "", "twitch_client_id": "", "twitch_channel": "",
    "youtube_video": "", "model": "gpt-4.1-mini",
    "transcribe_model": "gpt-4o-mini-transcribe", "speech_model": "gpt-4o-mini-tts",
    "voice": "coral", "screen": 0, "x": 30, "y": 60, "width": 440, "height": 480,
}
SECRET_NAMES = ("discord_token", "twitch_token", "youtube_token", "openai_key")
STORED_SECRET_NAMES = SECRET_NAMES + ("google_client_json", "twitch_refresh_token", "youtube_refresh_token")


class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def protect(data, decrypt=False, machine=False):
    if os.name != "nt":
        raise RuntimeError("Secret storage requires Windows DPAPI.")
    buf = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    result = Blob()
    dll = ctypes.WinDLL("crypt32", use_last_error=True)
    fn = dll.CryptUnprotectData if decrypt else dll.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    flags = 1 | (4 if machine and not decrypt else 0)
    if not fn(ctypes.byref(source), None, None, None, None, flags, ctypes.byref(result)):
        raise RuntimeError("Could not read or save secrets for this Windows user.")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        free = ctypes.WinDLL("kernel32").LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(result.data)


class Store:
    def __init__(self, path=None):
        self.lock = threading.RLock()
        self.path = Path(path or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OverlayRaceChat")
        self.sync_status = {}

    def load(self):
        self._sync()
        return self._load_local()

    def _load_local(self):
        config = dict(DEFAULTS)
        p = self.path / "settings.json"
        if p.exists():
            raw = json.loads(p.read_text(encoding="utf-8"))
            config.update({k: raw[k] for k in DEFAULTS if k in raw})
        return config

    def secrets(self):
        self._sync()
        return self._secrets_local()

    def _secrets_local(self):
        p = self.path / "secrets.dpapi"
        return json.loads(protect(p.read_bytes(), True)) if p.exists() else {}

    def _sync(self):
        if (self.path / 'profile-sync.json').exists():
            from racechat_profile_sync import synchronize, ensure_logon_hook
            result = synchronize(self.path)
            self.sync_status = {key: result[key] for key in ('configured', 'migration_pending')}
            ensure_logon_hook()

    def update_settings(self, changes):
        with self.lock:
            if (self.path / 'profile-sync.json').exists():
                from racechat_profile_sync import synchronize
                return synchronize(self.path, settings=changes)['config']
            config = self.load()
            config.update({k: v for k, v in changes.items() if k in DEFAULTS})
            self.save(config, self.secrets())
            return config

    def update_tokens(self, tokens):
        with self.lock:
            if (self.path / 'profile-sync.json').exists():
                from racechat_profile_sync import synchronize
                return synchronize(self.path, tokens=tokens)['credentials']
            credentials = self.secrets()
            credentials.update(tokens)
            self.save(self.load(), credentials)
            return credentials

    def save(self, config, secrets):
        with self.lock:
            if (self.path / 'profile-sync.json').exists():
                from racechat_profile_sync import synchronize
                synchronize(self.path, replacement=(config, secrets))
                return
            self._save(config, secrets)

    def _save(self, config, secrets):
        # Encrypt before touching existing files; never fall back to plaintext.
        encrypted = protect(json.dumps({k: secrets.get(k, "") for k in STORED_SECRET_NAMES}).encode())
        self.path.mkdir(parents=True, exist_ok=True)
        temp = self.path / "secrets.tmp"
        temp.write_bytes(encrypted)
        temp.replace(self.path / "secrets.dpapi")
        temp = self.path / "settings.tmp"
        temp.write_text(json.dumps({k: config.get(k, v) for k, v in DEFAULTS.items()}, indent=2), encoding="utf-8")
        temp.replace(self.path / "settings.json")
