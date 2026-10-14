"""App-owned protection with personally approved, portable helper provisioning."""
import atexit
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from allowed_applications import DEFAULT_ALLOWED, guard_exceptions, normalize as normalize_allowed


DEFAULTS = {"enabled": True, "mute_toasts": True, "focus_timeout": True,
            "firewall_notifications": True, "input_grace_ms": 2500, "alert_monitor": "auto",
            "redirect_always": True, "block_elevation": False, "allowed_apps": DEFAULT_ALLOWED}
UAC_STATUS = "not blocked, including administrators"


def monitors():
    """Read display topology, without changing resolution or window positions."""
    if os.name != "nt":
        return []
    import ctypes as c
    from ctypes import wintypes as w
    class Rect(c.Structure):
        _fields_ = [(name, w.LONG) for name in ("left", "top", "right", "bottom")]
    class Info(c.Structure):
        _fields_ = [("size", w.DWORD), ("bounds", Rect), ("work", Rect),
                    ("flags", w.DWORD), ("device", w.WCHAR * 32)]
    class Device(c.Structure):
        _fields_ = [("size", w.DWORD), ("name", w.WCHAR * 32), ("description", w.WCHAR * 128),
                    ("flags", w.DWORD), ("id", w.WCHAR * 128), ("key", w.WCHAR * 128)]
    callback_type = c.WINFUNCTYPE(w.BOOL, w.HMONITOR, w.HDC, c.POINTER(Rect), w.LPARAM)
    found = []
    def collect(handle, dc, rect, data):
        info = Info()
        info.size = c.sizeof(info)
        if c.windll.user32.GetMonitorInfoW(handle, c.byref(info)):
            r = info.bounds
            device = Device()
            device.size = c.sizeof(device)
            c.windll.user32.EnumDisplayDevicesW(info.device, 0, c.byref(device), 1)
            found.append({"device": info.device, "bounds": (r.left, r.top, r.right, r.bottom),
                          "primary": bool(info.flags & 1), "id": device.id or info.device,
                          "name": device.description})
        return True
    callback = callback_type(collect)
    c.windll.user32.EnumDisplayMonitors(None, None, callback, 0)
    primary = next((d for d in found if d["primary"]), None)
    for d in found:
        l, t, r, b = d["bounds"]
        d["upper"] = bool(primary and not d["primary"] and b <= primary["bounds"][1])
        name = d["device"].split("\\")[-1]
        d["label"] = f"{name} · {r-l}×{b-t}" + (" · upper" if d["upper"] else "")
        if d["name"]:
            d["label"] += f" · {d['name']}"
    return found


class RaceProtection:
    def __init__(self, settings=None):
        self.process = None
        self.error = ""
        self.last_launch = 0.0
        self.root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "OverlayApp" / "RaceProtection"
        if os.name == "nt":
            import ctypes
            session = ctypes.c_ulong()
            ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session))
            self.root /= f"Session-{session.value}"
        self.pause_file = self.root / "pausar.flag"
        self.settings = {**DEFAULTS, **(settings or {})}
        self.source = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "protection" / "bin"
        self.administrative = None
        self.administrative_error = ""
        self._admin_flags = None
        self._last_admin_wanted = set()
        self._setup_requested = False

    def _administrative_flags(self):
        from administrative_setup import AdministrativeSetup, WindowsBackend, wanted
        requested = wanted(self.settings)
        if requested and self.administrative is None and os.name == "nt":
            try:
                self.administrative = AdministrativeSetup(WindowsBackend(self.source.parent))
                self.administrative_error = ""
            except (OSError, ValueError) as error:
                self.administrative_error = "Administrative setup package unavailable: " + str(error)
        if self.administrative is not None:
            missing = self.administrative.inspect(self.settings, force=self._setup_requested)
            explicit = self._setup_requested and bool(requested)
            retry = bool(missing) and (explicit or (bool(requested - self._last_admin_wanted) and self.administrative.attempted))
            self.administrative.begin(self.settings, retry=retry, allow_running_game=explicit)
            ready = self.administrative.ready
            pending = self.administrative.pending
            # A pending request for a different feature must finish before this intent is consumed.
            if not pending or self.administrative.requested_features == requested:
                self._setup_requested = False
        else:
            ready = {}
            pending = bool(requested)
        if self.administrative is None or not self.administrative.pending or self.administrative.requested_features == requested:
            self._last_admin_wanted = requested
        return (bool("firewall" in requested and ready.get("firewall") and not pending),
                bool("elevation" in requested and ready.get("elevation") and not pending))

    def retry_administrative_setup(self):
        if self.administrative is None:
            self.configure(self.settings)
        if self.administrative is not None and not self.administrative.pending:
            self.administrative.begin(self.settings, retry=True, allow_running_game=True)
            self.configure(self.settings)

    def remove_administrative_helpers(self):
        if self.administrative is None and os.name == "nt":
            from administrative_setup import AdministrativeSetup, WindowsBackend
            try:
                self.administrative = AdministrativeSetup(WindowsBackend(self.source.parent))
            except (OSError, ValueError) as error:
                self.administrative_error = "Administrative removal unavailable: " + str(error)
                return
        if self.administrative is not None:
            self.configure({**self.settings, "mute_toasts": False, "firewall_notifications": False,
                            "block_elevation": False})
            self.administrative.begin(self.settings, remove=True, retry=True)

    def _binary(self):
        files = ("OverlayRaceGuard.exe", "config.json")
        digest = hashlib.sha256(b"".join((self.source / n).read_bytes() for n in files)).hexdigest()[:16]
        cache = self.root.parent / "bin" / digest
        cache.mkdir(parents=True, exist_ok=True)
        for name in files:
            target = cache / name
            if not target.exists():
                temporary = target.with_suffix(f".{os.getpid()}.tmp")
                shutil.copyfile(self.source / name, temporary)
                os.replace(temporary, target)
        return cache / files[0]

    def recover(self):
        if os.name != "nt":
            return
        try:
            subprocess.Popen([str(self._binary()), "--restore"], creationflags=subprocess.CREATE_NO_WINDOW,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.error = f"Recovery unavailable: {type(exc).__name__}"

    def configure(self, settings, *, request_setup=False):
        self.settings = {**DEFAULTS, **settings}
        self._setup_requested |= request_setup
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            config = json.loads((self.source / "config.json").read_text(encoding="utf-8-sig"))
            firewall_ready, elevation_ready = self._administrative_flags()
            self._admin_flags = (firewall_ready, elevation_ready)
            for key, name in (("mute_toasts", "MuteAppToasts"), ("focus_timeout", "ExtendForegroundTimeout"),
                              ("firewall_notifications", "SuppressFirewallPrompt"),
                              ("block_elevation", "BlockInteractiveElevation")):
                config[name] = bool(self.settings[key])
            config["MuteAppToasts"] &= firewall_ready
            config["SuppressFirewallPrompt"] &= firewall_ready
            config["BlockInteractiveElevation"] &= elevation_ready
            # The saved list survives mode changes; only effective runtime exceptions are suspended.
            exceptions = [] if self.settings["block_elevation"] else self.settings.get("allowed_apps", [])
            config["AllowedProcessNames"], config["AllowedExecutablePaths"] = guard_exceptions(exceptions)
            config["UserInputGraceMs"] = max(2000, min(15000, int(self.settings["input_grace_ms"])))
            destination = self.settings["alert_monitor"]
            if destination == "auto":
                destination = next((d.get("id", d["device"]) for d in monitors() if d["upper"]), "")
            config["AlertMonitor"] = destination or ""
            config["RouteAlways"] = bool(self.settings["redirect_always"])
            temporary = self.root / f"config-{os.getpid()}.tmp"
            temporary.write_text(json.dumps(config), encoding="utf-8")
            os.replace(temporary, self.root / "config.json")
            self.set_enabled(bool(self.settings["enabled"]))
            if self.settings["enabled"] and self.process is None:
                self.start()
        except (OSError, ValueError) as exc:
            self.error = f"Protection configuration unavailable: {type(exc).__name__}"

    def start(self):
        if os.name != "nt" or self.process is not None or not self.settings["enabled"]:
            return
        try:
            self.error = ""
            self.last_launch = time.time()
            binary = self._binary()
            self.root.mkdir(parents=True, exist_ok=True)
            # Configure before launch; configure's start recursion is avoided by this marker.
            self.process = False
            self.configure(self.settings)
            self.process = subprocess.Popen(
                [str(binary), "--run", "--owner", str(os.getpid()), "--config", str(self.root / "config.json")],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            atexit.register(self.close)
        except Exception as exc:
            self.process = None
            self.error = f"Protection unavailable: {type(exc).__name__}"

    def close(self):
        # Only release this app's lease. Another open OverlayApp retains protection.
        try:
            (self.root / f"owner-{os.getpid()}.json").unlink(missing_ok=True)
        except OSError:
            pass

    def set_enabled(self, enabled):
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            if enabled:
                self.pause_file.unlink(missing_ok=True)
            else:
                self.pause_file.write_text("pause", encoding="ascii")
        except OSError as exc:
            self.error = f"Protection control failed: {type(exc).__name__}"

    def status(self):
        status = self._runtime_status()
        if self.administrative is not None or self.administrative_error:
            status["Setup"] = self.administrative.status() if self.administrative is not None else self.administrative_error
        count = len(normalize_allowed(self.settings.get("allowed_apps", [])))
        status["ApplicationMode"] = (f"Block all requested; {count} saved exceptions suspended"
                                     if self.settings["block_elevation"] else f"Allow; {count} saved exceptions")
        if self.settings["block_elevation"] and "UAC" not in status:
            status["UAC"] = ("disabled" if not self.settings["enabled"] else "global blocking requested; runtime not confirmed")
        return status

    def _runtime_status(self):
        if self.administrative is not None:
            flags = self._administrative_flags()
            if flags != self._admin_flags:
                self.configure(self.settings)
        if self.error:
            return {"Mode": self.error, "Firewall": "unavailable"}
        if self.process is None and not self.settings["enabled"]:
            return {"Mode": "disabled", "Firewall": "disabled"}
        try:
            path = self.root / "status.json"
            if time.time() - path.stat().st_mtime > 5:
                raise OSError("stale")
            status = json.loads(path.read_text(encoding="utf-8-sig"))
            if self.administrative is not None or self.administrative_error:
                status["Setup"] = self.administrative.status() if self.administrative is not None else self.administrative_error
                if self.settings["enabled"]:
                    ready = self._admin_flags or (False, False)
                    if not ready[0] and (self.settings["mute_toasts"] or self.settings["firewall_notifications"]):
                        status.update(Mode="degraded", Degraded=True)
                        if self.settings["mute_toasts"]:
                            status["Toasts"] = "not applied; administrative setup not confirmed"
                        if self.settings["firewall_notifications"]:
                            status["Firewall"] = "not applied; administrative setup not confirmed"
                    if self.settings["block_elevation"] and not ready[1]:
                        status["UAC"] = "not blocked; administrative setup not confirmed"
            return status
        except (OSError, ValueError):
            if self.settings["enabled"] and not self.pause_file.exists() and time.time() - self.last_launch > 10:
                self.process = None
                self.start()
            return {"Mode": "waiting for component", "Firewall": "not confirmed"}

    def diagnostic_text(self):
        status = self.status()
        return (f"Protection: {status.get('Mode', 'not confirmed')}\n"
                f"Application mode: {status.get('ApplicationMode', 'not confirmed')}\n"
                f"Windows: {status.get('Windows', 'not confirmed')}\n"
                f"Routing: {status.get('Routing', 'not confirmed')}\n"
                f"Toasts: {status.get('Toasts', 'not confirmed')}\n"
                f"Focus: {status.get('Focus', 'not confirmed')}\n"
                f"Firewall: {status.get('Firewall', 'not confirmed')}\n"
                f"UAC: {status.get('UAC', UAC_STATUS)}\n"
                f"Logs: {self.root}\n"
                "Active/degraded describes the ordinary popup components, not UAC coverage.\n"
                "The optional global broker gate requires separate runtime confirmation.\n"
                f"Administrative setup: {status.get('Setup', 'not required or not checked')}\n"
                "Required helpers are installed/updated from the app after personal Windows approval.\n"
                "Blocked elevation can produce ordinary application error dialogs; window handling is best effort.\n"
                "Switch shortcuts and input events are preserved. Windows can reject operations on elevated windows.")
