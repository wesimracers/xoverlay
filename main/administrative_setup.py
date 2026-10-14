"""Portable, single-consent helper provisioning; no window/input automation."""
import ctypes
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid

COMPONENTS = {
    "firewall": ("OverlayRaceFirewall", "OverlayAppFirewall", "authorized-profiles.json"),
    "elevation": ("OverlayElevationGate", "OverlayElevationGate", "authorized-sids.json"),
}


def wanted(settings):
    if not settings.get("enabled"):
        return set()
    features = set()
    if settings.get("mute_toasts") or settings.get("firewall_notifications"):
        features.add("firewall")
    if settings.get("block_elevation"):
        features.add("elevation")
    return features


class WindowsBackend:
    @staticmethod
    def process_names():
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        class Entry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                        ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                        ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                        ("filename", w.WCHAR * 260)]
        kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError("Windows process inventory unavailable")
        try:
            entry = Entry()
            entry.size = ctypes.sizeof(Entry)
            more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            names = set()
            while more:
                names.add(entry.filename.lower())
                more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
            return names
        finally:
            kernel.CloseHandle(snapshot)

    def can_request(self):
        games = {"iracingsim64dx11.exe", "le mans ultimate.exe", "acs.exe", "acs_x86.exe", "assettocorsaevo.exe"}
        return not (self.process_names() & games)
    def __init__(self, source):
        self.source = Path(source)
        self.sid = self.user_sid() if os.name == "nt" else ""
        self.program_files = self.known_folder("905e63b6-c1bf-494e-b29c-65b732d3d21a") if os.name == "nt" else Path()
        self.program_data = self.known_folder("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97") if os.name == "nt" else Path()
        self.manifest = json.loads((self.source / "setup-manifest.json").read_text())

    @staticmethod
    def known_folder(folder):
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        ole = ctypes.WinDLL("ole32")
        guid = (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(folder).bytes_le)
        path = ctypes.c_wchar_p()
        shell.SHGetKnownFolderPath.argtypes = [ctypes.c_void_p, w.DWORD, w.HANDLE, ctypes.POINTER(ctypes.c_wchar_p)]
        ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        code = shell.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path))
        if code:
            raise OSError("Windows folder lookup failed")
        try:
            return Path(path.value)
        finally:
            ole.CoTaskMemFree(ctypes.cast(path, ctypes.c_void_p))

    @staticmethod
    def user_sid():
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel.GetCurrentProcess.restype = w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        advapi.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
        advapi.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
        token, size = w.HANDLE(), w.DWORD()
        if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 8, ctypes.byref(token)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p)).contents.value
            text = ctypes.c_wchar_p()
            if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                return text.value
            finally:
                kernel.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        finally:
            kernel.CloseHandle(token)

    @staticmethod
    def service_identity(name, executable):
        class Config(ctypes.Structure):
            _fields_ = [("type", w.DWORD), ("start", w.DWORD), ("error", w.DWORD),
                        ("binary", w.LPWSTR), ("group", w.LPWSTR), ("tag", w.DWORD),
                        ("dependencies", w.LPWSTR), ("account", w.LPWSTR), ("display", w.LPWSTR)]
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        advapi.OpenSCManagerW.argtypes = [w.LPCWSTR, w.LPCWSTR, w.DWORD]
        advapi.OpenSCManagerW.restype = w.HANDLE
        advapi.OpenServiceW.argtypes = [w.HANDLE, w.LPCWSTR, w.DWORD]
        advapi.OpenServiceW.restype = w.HANDLE
        advapi.QueryServiceConfigW.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
        advapi.CloseServiceHandle.argtypes = [w.HANDLE]
        manager = advapi.OpenSCManagerW(None, None, 1)
        service = None
        try:
            if not manager:
                return False
            service = advapi.OpenServiceW(manager, name, 1)
            if not service:
                return False
            size = w.DWORD()
            advapi.QueryServiceConfigW(service, None, 0, ctypes.byref(size))
            if not 0 < size.value < 65536:
                return False
            buffer = ctypes.create_string_buffer(size.value)
            if not advapi.QueryServiceConfigW(service, buffer, size, ctypes.byref(size)):
                return False
            config = ctypes.cast(buffer, ctypes.POINTER(Config)).contents
            return config.account == "LocalSystem" and config.binary.lower() == ('"' + str(executable) + '"').lower() and config.start in (2, 3)
        finally:
            if service:
                advapi.CloseServiceHandle(service)
            if manager:
                advapi.CloseServiceHandle(manager)

    def current(self, component):
        try:
            name, folder, metadata = COMPONENTS[component]
            executable = self.program_files / folder / (name + ".exe")
            if hashlib.sha256(executable.read_bytes()).hexdigest() != self.manifest[component]:
                return False
            marker = json.loads((self.program_data / folder / "managed-setup.json").read_text(encoding="utf-8-sig"))
            if marker.get("Schema") != 1 or marker.get("Complete") is not True or marker.get("Service") != name or marker.get("Hash") != self.manifest[component]:
                return False
            entries = json.loads((self.program_data / folder / metadata).read_text(encoding="utf-8-sig"))
            if not isinstance(entries, list):
                entries = [entries]
            sids = [entry["SID"] if isinstance(entry, dict) else entry for entry in entries]
            return self.sid in sids and self.service_identity(name, executable)
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def request(self, features, remove=False):
        """Use normal ShellExecute consent; never approve or manipulate its desktop."""
        executable = self.source / "OverlayProtectionSetup.exe"
        if hashlib.sha256(executable.read_bytes()).hexdigest() != self.manifest["installer"]:
            raise OSError("Packaged setup verification failed")
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        shell = ctypes.WinDLL("shell32", use_last_error=True)
        ole = ctypes.WinDLL("ole32")
        class ProcessEntry(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                        ("heap", ctypes.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                        ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                        ("filename", w.WCHAR * 260)]
        kernel.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
        kernel.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise OSError("Windows approval inventory unavailable")
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(ProcessEntry)
            has_entry = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while has_entry:
                if entry.filename.lower() in ("consent.exe", "credentialuibroker.exe"):
                    raise OSError("Another Windows approval is already pending; resolve it before retrying")
                has_entry = kernel.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel.CloseHandle(snapshot)
        class Security(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", w.BOOL)]
        class Execute(ctypes.Structure):
            _fields_ = [("size", w.DWORD), ("mask", w.ULONG), ("hwnd", w.HWND),
                        ("verb", w.LPCWSTR), ("file", w.LPCWSTR), ("parameters", w.LPCWSTR),
                        ("directory", w.LPCWSTR), ("show", ctypes.c_int), ("instance", w.HINSTANCE),
                        ("idlist", ctypes.c_void_p), ("class_name", w.LPCWSTR), ("class_key", w.HKEY),
                        ("hotkey", w.DWORD), ("icon", w.HANDLE), ("process", w.HANDLE)]
        kernel.CreateMutexW.argtypes = [ctypes.POINTER(Security), w.BOOL, w.LPCWSTR]
        kernel.CreateMutexW.restype = w.HANDLE
        kernel.OpenMutexW.argtypes = [w.DWORD, w.BOOL, w.LPCWSTR]
        kernel.OpenMutexW.restype = w.HANDLE
        kernel.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        kernel.ReleaseMutex.argtypes = [w.HANDLE]
        kernel.CloseHandle.argtypes = [w.HANDLE]
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [w.LPCWSTR, w.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        shell.ShellExecuteExW.argtypes = [ctypes.POINTER(Execute)]
        descriptor = ctypes.c_void_p()
        if not advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW("D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;0x00100001;;;AU)", 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        security = Security(ctypes.sizeof(Security), descriptor, False)
        mutex = kernel.CreateMutexW(ctypes.byref(security), False, "Global\\OverlayProtectionConsentRequest")
        if not mutex and ctypes.get_last_error() == 5:
            mutex = kernel.OpenMutexW(0x00100001, False, "Global\\OverlayProtectionConsentRequest")
        kernel.LocalFree(descriptor)
        if not mutex:
            raise OSError("Administrative setup lock unavailable")
        owned = False
        initialized = False
        try:
            owned = kernel.WaitForSingleObject(mutex, 0) in (0, 0x80)
            if not owned:
                raise OSError("Another Overlay administrative request is in progress")
            initialized = ole.CoInitializeEx(None, 6) >= 0
            request_id = str(uuid.uuid4())
            args = ["--user-sid:" + self.sid, "--request-id:" + request_id]
            args.extend("--" + feature for feature in sorted(features))
            if remove:
                args.append("--remove")
            info = Execute()
            info.size = ctypes.sizeof(Execute)
            info.mask = 0x40 | 0x100 | 0x400
            info.verb = "runas"
            info.file = str(executable)
            info.parameters = " ".join(args)
            info.directory = str(self.source)
            info.show = 0
            if not shell.ShellExecuteExW(ctypes.byref(info)):
                error = ctypes.get_last_error()
                if error == 1223:
                    return 1223, "Personal administrative approval was cancelled."
                raise ctypes.WinError(error)
            if not info.process:
                raise OSError("Setup process was not confirmed")
            try:
                kernel.WaitForSingleObject(info.process, 0xFFFFFFFF)
                exit_code = w.DWORD()
                if not kernel.GetExitCodeProcess(info.process, ctypes.byref(exit_code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                result_file = self.program_data / "OverlayProtectionSetup" / (request_id + ".json")
                try:
                    result = json.loads(result_file.read_text(encoding="utf-8-sig"))
                    message = result["Message"] if result["Id"] == request_id else "Setup result was not confirmed."
                except (OSError, ValueError, KeyError):
                    message = "Setup completed without a confirmed result; see component status."
                return exit_code.value, message
            finally:
                kernel.CloseHandle(info.process)
        finally:
            if initialized:
                ole.CoUninitialize()
            if owned:
                kernel.ReleaseMutex(mutex)
            kernel.CloseHandle(mutex)


class AdministrativeSetup:
    def __init__(self, backend, clock=time.monotonic):
        self.backend = backend
        self.clock = clock
        self.ready = {key: False for key in COMPONENTS}
        self.pending = False
        self.requested_features = set()
        self.attempted = False
        self.removing = False
        self.message = "Administrative requirements have not been checked."
        self.started = 0
        self.last_probe = -100
        self.deferred_remove = False
        self.deferred_retry = False
        self.lock = threading.Lock()

    def inspect(self, settings, force=False):
        if self.clock() - self.last_probe >= 2 or force:
            self.last_probe = self.clock()
            for feature in wanted(settings):
                self.ready[feature] = self.backend.current(feature)
        return wanted(settings) - {key for key, ready in self.ready.items() if ready}

    def begin(self, settings, remove=False, retry=False, allow_running_game=False):
        remove = remove or self.deferred_remove
        retry = retry or self.deferred_retry
        missing = self.inspect(settings)
        features = set(COMPONENTS) if remove else wanted(settings)
        with self.lock:
            if self.pending or (self.attempted and not retry) or (not missing and not remove and not retry):
                if not missing and not self.pending and not self.attempted:
                    self.message = "Administrative helpers are current; runtime coverage is verified separately."
                return
            if hasattr(self.backend, "can_request"):
                try:
                    if not self.backend.can_request() and not allow_running_game:
                        self.deferred_remove = remove
                        self.deferred_retry = retry
                        self.message = "Administrative setup/removal deferred until supported games close; no permission request is open."
                        return
                except OSError:
                    self.message = "Game state could not be verified; administrative requests are deferred."
                    return
            self.pending = True
            self.requested_features = features
            self.attempted = True
            self.removing = remove
            self.deferred_remove = False
            self.deferred_retry = False
            self.started = self.clock()
            self.message = "Awaiting personal Windows approval/setup; no second request will be sent."
        def run():
            try:
                # Give the ordinary guard time to publish disabled privileged leases.
                time.sleep(2)
                code, message = self.backend.request(features, remove=remove)
                self.message = message
                if code == 0:
                    self.inspect(settings, force=True)
                    if not remove and self.inspect(settings):
                        self.message = "Setup did not confirm every required helper; administrative coverage is unavailable."
            except Exception as error:
                native_code = getattr(error, "winerror", None)
                detail = "Windows error " + str(native_code) if native_code else str(error)
                self.message = "Administrative setup unavailable: " + detail
            finally:
                self.pending = False
                if remove:
                    self.ready = {key: False for key in COMPONENTS}
        threading.Thread(target=run, name="Overlay administrative setup", daemon=True).start()

    def status(self):
        if self.pending and self.clock() - self.started > 60:
            return "Windows approval/setup has not completed; no automatic retry."
        return self.message
