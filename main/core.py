# core
import os, sys, json, time, shutil, math
from collections import defaultdict, deque

from PyQt6.QtGui import QColor, QFont

import irsdk
from blacklist import BlacklistStore, normalize_user_id
from sector_timing import SectorHistory, SECTOR_COLUMNS, sector_columns
from rpm_state import seed_rpm_config


# =============================
# PATHS
# =============================

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
if not os.path.exists(os.path.join(BASE_DIR, "overlay.json")):
    BASE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "OverlayApp", "Settings")
CONFIG_FILE = os.path.join(BASE_DIR, "overlay.json")
LOG_FILE    = os.path.join(BASE_DIR, "overlay.log")
DEBUG_ARCHIVE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "OverlayApp", "Captures")
DEBUG_RETENTION_DAYS = 10
# DATA_FILE is set below after reading the config — name includes datetime when debug=ENABLE
DATA_FILE = os.path.join(DEBUG_ARCHIVE_DIR, "data.json")
BLACKLIST_FILE = os.path.join(BASE_DIR, "blacklist.json")
blacklist_store = BlacklistStore(BLACKLIST_FILE)


def blacklist_ids():
    return blacklist_store.current_ids()


def is_driver_blacklisted(driver):
    user_id = normalize_user_id(driver.get("UserID")) if isinstance(driver, dict) else None
    return user_id is not None and user_id in blacklist_ids()

# =============================
# LOGGING
# =============================

_LOG_INITIALIZED = [False]
_LOG_MAX_BYTES = 2_000_000  # 261001_CURSOR

# Always truncate log on each overlay start
# try:
#     with open(LOG_FILE, "w", encoding="utf-8") as _f:
#         pass
#     _LOG_INITIALIZED[0] = True
# except Exception:
#     pass


def _rotate_log_if_needed():  # 261001_CURSOR
    try:  # 261001_CURSOR
        if os.path.isfile(LOG_FILE) and os.path.getsize(LOG_FILE) >= _LOG_MAX_BYTES:  # 261001_CURSOR
            previous = LOG_FILE + ".1"  # 261001_CURSOR
            if os.path.exists(previous):  # 261001_CURSOR
                os.remove(previous)  # 261001_CURSOR
            os.replace(LOG_FILE, previous)  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        pass  # 261001_CURSOR


def _log(msg: str):
    try:
        _rotate_log_if_needed()  # 261001_CURSOR
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        # mode = "w" if not _LOG_INITIALIZED[0] else "a"
        # _LOG_INITIALIZED[0] = True
        # with open(LOG_FILE, mode, encoding="utf-8") as f:
        with open(LOG_FILE, "a", encoding="utf-8") as f:  # 261001_CURSOR
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def _prepare_debug_archive():
    """Move legacy captures out of dist and prune captures after 10 days."""
    try:
        os.makedirs(DEBUG_ARCHIVE_DIR, exist_ok=True)
    except Exception as exc:
        _log(f"Debug archive create error: {exc!r}")
        return

    try:
        if os.path.abspath(BASE_DIR) != os.path.abspath(DEBUG_ARCHIVE_DIR):
            for name in os.listdir(BASE_DIR):
                is_capture = (
                    name == "data.json"
                    or (name.startswith("data_") and name.endswith(".json"))
                )
                is_report = (
                    name.startswith("relative_reports_")
                    and name.endswith(".jsonl")
                )
                if not (is_capture or is_report):
                    continue
                source = os.path.join(BASE_DIR, name)
                if not os.path.isfile(source):
                    continue
                destination = os.path.join(DEBUG_ARCHIVE_DIR, name)
                if os.path.exists(destination):
                    stem, ext = os.path.splitext(name)
                    destination = os.path.join(
                        DEBUG_ARCHIVE_DIR,
                        f"{stem}_{int(os.path.getmtime(source))}{ext}",
                    )
                shutil.move(source, destination)
    except Exception as exc:
        _log(f"Debug archive move error: {exc!r}")

    try:
        cutoff = time.time() - (DEBUG_RETENTION_DAYS * 86400)
        for name in os.listdir(DEBUG_ARCHIVE_DIR):
            is_capture = (
                name == "data.json"
                or (name.startswith("data_") and name.endswith(".json"))
            )
            is_report = (
                name.startswith("relative_reports_")
                and name.endswith(".jsonl")
            )
            if not (is_capture or is_report):
                continue
            path = os.path.join(DEBUG_ARCHIVE_DIR, name)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
    except Exception as exc:
        _log(f"Debug archive retention error: {exc!r}")


def save_cfg():
    """Write in-memory cfg back to overlay.json."""
    try:
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_FILE)
    except Exception as e:
        _log(f"save_cfg error: {e!r}")


def _reset_jsonl_file():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass


def _append_jsonl(obj: dict):
    try:
        obj["_ts"] = time.time()
        with open(DATA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


# =============================
# CONFIG
# =============================

def load_cfg():
    fresh = not os.path.exists(CONFIG_FILE)
    source = os.path.join(_BUNDLE_DIR, "factory-overlay.json") if fresh else CONFIG_FILE
    with open(source, "r", encoding="utf-8-sig") as f:
        cfg = json.load(f)
    cfg["_fresh_factory_layout"] = fresh or bool(cfg.get("_fresh_factory_layout"))

    cfg.setdefault("debug", False)
    cfg.setdefault("ui", {})
    cfg["ui"].setdefault("font_family", "Consolas")
    cfg["ui"].setdefault("font_size", 10)
    cfg["ui"].setdefault("row_height", 18)
    cfg["ui"].setdefault("padding_x", 3)
    cfg["ui"].setdefault("padding_y", 3)
    cfg["ui"].setdefault("update_ms", 10)

    cfg.setdefault("windows", {}).setdefault("longest_sector", {
        "x": 100, "y": 100, "width": 328, "height": 1000,
        "enabled": False, "show_in_garage": False, "font_size": 0,
    })
    sector_settings = cfg.setdefault("longest_sector_settings", {})
    sector_settings.setdefault("update_ms", 100)
    sector_settings["columns"] = sector_columns(sector_settings.get("columns"))

    seed_rpm_config(cfg)

    return cfg


cfg = load_cfg()
UI = cfg["ui"]

# Debug: stored as "ENABLE" / "DISABLE" string (legacy bool also accepted).
# Consolidated at root cfg["debug"] — the old cfg["general"]["debug"] is ignored.
_raw_debug = cfg.get("debug", "DISABLE")
DEBUG = (str(_raw_debug).upper() == "ENABLE") or (_raw_debug is True)

# When debug is enabled every overlay start gets its own timestamped data file
# so multiple sessions can be kept as separate backups.
if DEBUG:
    DATA_FILE = os.path.join(
        DEBUG_ARCHIVE_DIR, f"data_{time.strftime('%Y%m%d_%H%M%S')}.json"
    )
else:
    DATA_FILE = os.path.join(DEBUG_ARCHIVE_DIR, "data.json")

ROW_H = int(UI.get("row_height", 18))
PAD_X = int(UI.get("padding_x", 3))
PAD_Y = int(UI.get("padding_y", 3))
UPDATE_MS = int(UI.get("update_ms", 10))

FONT_NORMAL = QFont(UI.get("font_family", "Consolas"), int(UI.get("font_size", 10)))
FONT_BOLD = QFont(UI.get("font_family", "Consolas"), int(UI.get("font_size", 10)))
FONT_BOLD.setBold(True)

CLR_WHITE = QColor(255, 255, 255)
CLR_BLACK = QColor(0, 0, 0)
CLR_GREEN = QColor(0, 255, 0)
CLR_RED = QColor(255, 0, 0)
CLR_GRID = QColor(70, 70, 70)
CLR_ROW_A = QColor(0, 0, 0)
CLR_ROW_B = QColor(25, 25, 25)
CLR_PLAYER_BG = QColor(255, 255, 255)

_CLASS_COLORS = [
    QColor(120, 200, 255),
    QColor(255, 160, 120),
    QColor(170, 255, 140),
    QColor(255, 220, 120),
    QColor(200, 160, 255),
    QColor(255, 120, 200),
    QColor(140, 255, 240),
    QColor(255, 255, 140),
]


def class_color(cid: int) -> QColor:
    try:
        return _CLASS_COLORS[int(cid) % len(_CLASS_COLORS)]
    except Exception:
        return CLR_WHITE


# =============================
# IRSDK
# =============================


def _install_pyirsdk_frozen_buffer_fix():
    """Backport pyirsdk 1.3.6's coherent frozen-buffer read to 1.3.5.

    pyirsdk 1.3.5 stores a frozen buffer but its getter ignores it, so a
    multi-field widget can silently read two different telemetry ticks.  The
    installed runtime and the bundled source are both 1.3.5.
    """
    try:
        def _var_buffer_latest(sdk):
            frozen = getattr(sdk, "_IRSDK__var_buffer_latest", None)
            if frozen is not None:
                return frozen
            buffers = sorted(
                sdk._header.var_buf,
                key=lambda value: value.tick_count,
                reverse=True,
            )
            if not buffers:
                return None
            return buffers[1] if len(buffers) > 1 else buffers[0]

        irsdk.IRSDK._var_buffer_latest = property(_var_buffer_latest)
    except Exception as exc:
        _log(f"pyirsdk frozen-buffer compatibility error: {exc!r}")


_install_pyirsdk_frozen_buffer_fix()
ir = irsdk.IRSDK()

# pyirsdk caches the variable-name -> header-position map for the lifetime of
# the connection. iRacing can reorder that table when the car changes while
# keeping the shared-memory connection alive. The old map then reads unrelated
# values at valid offsets (for example tyre wear becomes engine RPM). Keep a
# small generation record and rebuild only pyirsdk's telemetry view; YAML and
# the simulator connection remain intact.
_TELEMETRY_LAYOUT = {
    "root": None,
    "generation": 0,
    "last_reason": "",
    "last_refresh_t": 0.0,
}
_TELEMETRY_SENTINELS = (
    "SessionTime",
    "PlayerCarIdx",
    "CarIdxLapDistPct",
    "FuelLevel",
    "FuelUsePerHour",
    "LFtempCL",
    "RRtempCR",
)


def _telemetry_root_signature():
    try:
        header = ir._header
        if header is None:
            return None
        return (
            int(header.num_vars),
            int(header.var_header_offset),
            int(header.num_buf),
            int(header.buf_len),
        )
    except Exception:
        return None


def _refresh_telemetry_layout(reason="layout changed"):
    """Re-read live buffer geometry and variable headers without disconnecting."""
    try:
        if not ir.is_initialized or ir._shared_mem is None:
            return False
        try:
            ir.unfreeze_var_buffer_latest()
        except Exception:
            pass

        # Header.var_buf stores buf_len at construction time, so rebuild the
        # Header as well as the three lazy variable-header caches.
        ir._header = irsdk.Header(ir._shared_mem)
        setattr(ir, "_IRSDK__var_headers", None)
        setattr(ir, "_IRSDK__var_headers_dict", None)
        setattr(ir, "_IRSDK__var_headers_names", None)

        _TELEMETRY_LAYOUT["root"] = _telemetry_root_signature()
        _TELEMETRY_LAYOUT["generation"] += 1
        _TELEMETRY_LAYOUT["last_reason"] = str(reason)
        _TELEMETRY_LAYOUT["last_refresh_t"] = time.time()
        if DEBUG:
            _log(
                "Telemetry layout refreshed: "
                f"generation={_TELEMETRY_LAYOUT['generation']} "
                f"root={_TELEMETRY_LAYOUT['root']} reason={reason}"
            )
        return True
    except Exception as exc:
        _log(f"Telemetry layout refresh error ({reason}): {exc!r}")
        return False


def _ensure_telemetry_layout(name=None):
    """Detect geometry changes and stale cached name mappings before reads."""
    if not ir.is_initialized or ir._header is None:
        return

    current_root = _telemetry_root_signature()
    previous_root = _TELEMETRY_LAYOUT.get("root")
    if previous_root is None:
        _TELEMETRY_LAYOUT["root"] = current_root
    elif current_root != previous_root:
        _refresh_telemetry_layout(
            f"root {previous_root} -> {current_root}"
        )
        return

    try:
        cached = getattr(ir, "_IRSDK__var_headers_dict", None)
        if not cached:
            return
        checks = (name,) if name else _TELEMETRY_SENTINELS
        for key in checks:
            if not key:
                continue
            header = cached.get(key)
            if header is not None and header.name != key:
                _refresh_telemetry_layout(
                    f"cached {key!r} now points to {header.name!r}"
                )
                return
    except Exception as exc:
        if DEBUG:
            _log(f"Telemetry layout validation error: {exc!r}")


def telemetry_layout_status(include_fields=False):
    """Return compact diagnostics for debug captures and widget payloads."""
    _ensure_telemetry_layout()
    root = _telemetry_root_signature()
    result = {
        "generation": int(_TELEMETRY_LAYOUT.get("generation", 0)),
        "root": list(root) if root else None,
        "last_reason": _TELEMETRY_LAYOUT.get("last_reason", ""),
    }
    try:
        cached = getattr(ir, "_IRSDK__var_headers_dict", None)
        if include_fields and cached is None and ir.is_initialized:
            cached = ir._var_headers_dict
        result["cached_fields"] = len(cached) if cached else 0
        mismatches = []
        if cached:
            for key in _TELEMETRY_SENTINELS:
                header = cached.get(key)
                if header is not None and header.name != key:
                    mismatches.append([key, header.name])
        result["mapping_ok"] = not mismatches
        if mismatches:
            result["mismatches"] = mismatches

        if include_fields and cached:
            fields = {}
            for key in _CAPTURE_TYRE_FIELDS + (
                "FuelLevel", "FuelLevelPct", "FuelUsePerHour",
                "CarIdxLapDistPct", "CarIdxEstTime",
            ):
                header = cached.get(key)
                if header is None:
                    fields[key] = None
                    continue
                fields[key] = {
                    "actual_name": header.name,
                    "offset": int(header.offset),
                    "type": int(header.type),
                    "count": int(header.count),
                    "unit": header.unit,
                }
            result["fields"] = fields
    except Exception as exc:
        result["diagnostic_error"] = repr(exc)
    return result


def connect():
    """Ensure pyirsdk is bound to iRacing's shared memory.

    On first call (`is_initialized=False`) we run `ir.startup()` to bind to
    the shared memory file. On subsequent calls we just return the live
    `is_connected` flag. We do not close/rebind on session boundaries:
    iRacing keeps shared memory valid, while the soft reset path refreshes
    both YAML state and pyirsdk's car-specific variable-header view.

    If `startup()` itself throws (e.g. iRacing closed mid-launch), force
    `shutdown()` so the next tick gets a clean retry instead of staying
    stuck in a half-initialised state."""
    try:
        if not ir.is_initialized:
            ir.startup()
            _TELEMETRY_LAYOUT["root"] = _telemetry_root_signature()
        _ensure_telemetry_layout()
        return ir.is_connected
    except Exception as e:
        _log(f"connect error: {e!r}")
        try:
            ir.shutdown()
        except Exception:
            pass
        return False


_LAYOUT_CHECK_T = [0.0]  # 261001_CURSOR


def sg(name, default=None):
    try:
        # _ensure_telemetry_layout(name)
        now_layout = time.monotonic()  # 261001_CURSOR
        if now_layout - _LAYOUT_CHECK_T[0] >= 0.1:  # 261001_CURSOR
            _LAYOUT_CHECK_T[0] = now_layout  # 261001_CURSOR
            _ensure_telemetry_layout(name)  # 261001_CURSOR
        return ir[name]
    except Exception:
        return default


def begin_frame():  # 261001_CURSOR
    """Freeze one telemetry tick and update session state at most 20 times a second."""  # 261001_CURSOR
    connected = False  # 261001_CURSOR
    try:  # 261001_CURSOR
        connected = bool(connect())  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        connected = False  # 261001_CURSOR
    if connected:  # 261001_CURSOR
        try:  # 261001_CURSOR
            ir.freeze_var_buffer_latest()  # 261001_CURSOR
        except Exception:  # 261001_CURSOR
            pass  # 261001_CURSOR
        update_state_and_debug_dump()  # 261001_CURSOR
    return connected  # 261001_CURSOR


def player_idx():
    v = sg("PlayerCarIdx", None)
    if v is None:
        v = sg("DriverCarIdx", 0)
    try:
        return int(v)
    except Exception:
        return 0


def session_time():
    try:
        return float(sg("SessionTime", 0.0) or 0.0)
    except Exception:
        return 0.0


# =============================
# HELPERS
# =============================


def _safe_int(x, default=0):
    try:
        return int(float(x))
    except Exception:
        return default

def _safe_float(x, default=0.0):
    try:
        return float(x)
    except Exception:
        return default

def pit_last_duration(car_idx: int, drv: dict):
    # seconds (float) or None
    try:
        v = db_get_car_field(drv, car_idx, "lastpit_dur", "")
        if v == "" or v is None:
            return None
        return float(v)
    except Exception:
        return None

def pit_last_lap(car_idx: int, drv: dict):
    try:
        v = db_get_car_field(drv, car_idx, "lastpit_lap", "")
        if v == "" or v is None:
            return 0
        return int(float(v))
    except Exception:
        return 0

def pit_last_time_str(car_idx: int):
    dm = driver_map()
    drv = dm.get(car_idx, {}) if dm else {}
    dur = pit_last_duration(car_idx, drv)
    if dur is None:
        return ""
    return str(int(round(dur))) if dur >= 100 else f"{dur:.1f}"

def laps_since_pit(car_idx):
    try:
        dm = driver_map()
        drv = dm.get(car_idx, {}) if dm else {}

        cl = sg("CarIdxLapCompleted", [])
        if not cl or len(cl) <= car_idx:
            return ""

        curr = _safe_int(cl[car_idx], 0)
        if curr <= 0:
            return ""

        # 1) prefer runtime last_pit_lap_completed
        pl = _safe_int(last_pit_lap_completed.get(car_idx, 0), 0)

        # 2) fallback to persisted last pit lap
        if pl <= 0 and drv:
            pl = pit_last_lap(car_idx, drv)

        if pl <= 0:
            return ""

        v = curr - pl
        if v < 0:
            return ""

        out = str(v)
        if drv:
            db_set_car_field(drv, car_idx, "lppit", out)
        return out
    except Exception:
        return ""

def pit_time(car_idx):
    """Display pit-stop time.

    While CURRENTLY on pit road : live timer since entry, but suppressed
        for the first PIT_LIVE_GRACE seconds so a brief CarIdxOnPitRoad
        flicker (boundary noise, tow re-entry) doesn't flash a sub-1s
        garbage value. During the grace window we show the previously
        persisted duration instead (or blank if no prior pit).
    After leaving                : show last persisted pit duration, but
        only when it's at least PIT_MIN_DISPLAY seconds — short stored
        values from pre-fix data or surviving flickers stay hidden.
    """
    PIT_LIVE_GRACE = 3.0    # don't trust an "on pit" toggle for the first 3s
    PIT_MIN_DISPLAY = 5.0   # any persisted dur below this is presumed bogus

    try:
        dm = driver_map()
        drv = dm.get(car_idx, {}) if dm else {}

        # Helper: render the last-persisted duration, gated by min threshold
        def _show_persisted():
            if not drv:
                return ""
            d = pit_last_duration(car_idx, drv)
            if d is None or d < PIT_MIN_DISPLAY:
                return ""
            return str(int(round(d))) if d >= 100 else f"{d:.1f}"

        if bool(prev_on_pit.get(car_idx, False)):
            t0 = pit_entry_time.get(car_idx)
            if not t0:
                return _show_persisted()
            dt = session_time() - float(t0)
            if dt < 0:
                return _show_persisted()
            if dt < PIT_LIVE_GRACE:
                # still inside grace — show prior good value, not the new <1s noise
                return _show_persisted()
            return str(int(round(dt))) if dt >= 100 else f"{dt:.1f}"

        return _show_persisted()
    except Exception:
        return ""


def fmt_time_1(sec):
    try:
        sec = float(sec)
    except Exception:
        return ""
    if sec <= 0 or sec > 99999:
        return ""
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}:{s:04.1f}" if m else f"{s:.1f}"


def fmt_sec_abs(delta):
    try:
        d = float(delta)
    except Exception:
        return "", CLR_WHITE
    s = abs(d)
    txt = str(int(round(s))) if s >= 100 else f"{s:.1f}"
    if txt in ("0.0", "0"):
        return "0", CLR_WHITE
    return txt, (CLR_GREEN if d > 0 else CLR_RED)


def brand3(v):
    return str(v or "").strip()[:3].upper()


def flag3(v):
    return str(v or "").strip()[:3].upper()


def tire_letter(compound):
    try:
        c = int(compound)
    except Exception:
        return ""
    return "H" if c == 0 else ("W" if c == 1 else "")


def driver_map():
    di = sg("DriverInfo", None) or {}
    out = {}
    for d in (di.get("Drivers") or []):
        try:
            out[int(d.get("CarIdx"))] = d
        except Exception:
            pass
    return out


def delta_seconds(car_idx, ref_idx):
    if ref_idx is None:
        return None
    f2 = sg("CarIdxF2Time", [])
    if f2 and len(f2) > max(car_idx, ref_idx):
        try:
            return float(f2[car_idx]) - float(f2[ref_idx])
        except Exception:
            pass
    return None

def _normalize_lap_time_sec(v):
    """Return a sane lap time in seconds, else None."""
    try:
        sec = float(v)
    except Exception:
        return None
    if not (20.0 <= sec <= 2000.0):
        return None
    return sec


def session_best_lap(car_idx: int):
    """Best lap seen this session for this car, including invalid laps."""
    try:
        return _normalize_lap_time_sec(_session_best_lap_sec.get(int(car_idx)))
    except Exception:
        return None


def session_laps(car_idx: int):
    """Completed lap times seen this session for one car.

    This intentionally includes laps iRacing may mark invalid; the overlay's
    BEST column follows the user's rule: fastest completed lap wins.
    """
    try:
        return list(_session_all_laps_sec.get(int(car_idx), []))
    except Exception:
        return []


def session_best_lap_update(car_idx: int, lap_time_sec):
    """Update the per-session best lap tracker from all completed laps."""
    sec = _normalize_lap_time_sec(lap_time_sec)
    if sec is None:
        return
    try:
        ci = int(car_idx)
        _session_all_laps_sec[ci].append(sec)
        prev = _session_best_lap_sec.get(ci)
        if prev is None or sec < prev:
            _session_best_lap_sec[ci] = sec
    except Exception:
        pass


def best_last(car_idx):
    b = sg("CarIdxBestLapTime", [])
    l = sg("CarIdxLastLapTime", [])

    best = ""
    last = ""

    best_sec = session_best_lap(car_idx)
    if best_sec is None and b and len(b) > car_idx:
        best_sec = _normalize_lap_time_sec(b[car_idx])
    if best_sec is not None:
        best = fmt_time_1(best_sec)

    if l and len(l) > car_idx:
        last_sec = _normalize_lap_time_sec(l[car_idx])
        if last_sec is not None:
            last = fmt_time_1(last_sec)

    return best, last


# =============================
# SAFETY CAR CHECK (MISSING BEFORE)
# =============================

def _is_safety_car(drv: dict) -> bool:
    try:
        if drv.get("CarIsPaceCar"):
            return True
    except Exception:
        pass
    try:
        if brand3(drv.get("CarScreenNameShort", "")) == "SAF":
            return True
    except Exception:
        pass
    return False


# =============================
# RUNTIME STATE
# =============================

start_class_pos = {}
pit_entry_time = {}
last_pit_lap_completed = {}
prev_on_pit = defaultdict(bool)
lap_hist = defaultdict(lambda: deque(maxlen=30))  # valid laps only (no pit laps, no incident laps)
last_lap_completed = defaultdict(int)
_pit_laps = defaultdict(set)  # car_idx -> lap numbers excluded (in-lap + out-lap after pit stop)
_inc_at_sf = {}               # car_idx -> incident count at last S/F crossing
_last_pit_lap = {}
_prev_pit_state = {}
_inc_cache = {}      # car_idx -> accumulated incident points (never decreases within session)
_inc_prev_raw = {}   # car_idx -> last raw CarIdxIncidentCount value (for delta tracking)
# Per-car heuristic incident detection state (for non-player cars where
# iRacing does NOT broadcast CarIdxIncidentCount during race).
#   _inc_surf_prev    : last seen CarIdxTrackSurface value per car
#   _inc_offtrack_t   : SessionTime when current off-track-state started
#   _inc_offtrack_until: don't double-count within this cooldown window
#   _inc_dp_hist      : deque of (t, dp) for spin / stopped-car detection
#   _inc_stopped_until: cooldown after counting a stopped-car incident
# Together these support:
#   +1 incident when car transitions OnTrack(3) → OffTrack(0) and STAYS
#     off-track for at least 0.5s (filters single-wheel slight excursions)
#   +2 incidents when car's LapDistPct stops advancing while race is green
#     and the car is on track (likely spun or stopped)
# Crash detection (+4) is too noisy with telemetry alone — left out.
_inc_surf_prev = {}
_inc_offtrack_t = {}
_inc_offtrack_until = {}
_inc_dp_hist = {}
_inc_stopped_until = {}
# Track when each car most recently entered "stopped on track" state, used by
# the crash detector to find pairs of cars that stopped at the same location
# at the same time — a strong signal of car-to-car contact.
_inc_stopped_at = {}      # car_idx -> (session_time, dp) when stopped
_inc_crash_until = {}     # car_idx -> cooldown timestamp after a crash hit
_inc_stop_score = {}      # car_idx -> score already applied for current stop
_qualify_class_pos = {}   # car_idx -> class_pos from most recent Qualify session (persists into Race)
_EVENT_SIG = [None]       # (SessionID, TrackName) — changes only with a new event, not between sessions

# --- Sector timing ---
_sf_cross_time = {}       # car_idx -> session_time of last S/F crossing
_sector_cross_time = {}   # car_idx -> {sector_idx: session_time} of last crossing in current lap
_sector_pcts = []         # sorted sector boundary fracs (0 < pct < 1); excludes S/F at 0.0
_sector_next_retry_t = [0.0]
_sector_missing_logged = [False]
sector_history = SectorHistory()
_sector_inc_at_sf = {}
_sector_prev_sample_t = {}
_sector_track_key = [None]
_prev_dp = {}             # car_idx -> dist_pct from previous frame (sector crossing detection)
_session_best_lap_sec = {}  # car_idx -> fastest completed lap seen in this session (valid or invalid)
_session_all_laps_sec = defaultdict(list)  # car_idx -> every sane completed lap seen this session


def reset_lap_history():
    """Discard rolling averages and completion/incident anchors for a new session."""
    lap_hist.clear()
    last_lap_completed.clear()
    _inc_at_sf.clear()


def init_start_positions():
    if start_class_pos:
        return
    cps = sg("CarIdxClassPosition", [])
    if not cps:
        return
    for i, cp in enumerate(cps):
        try:
            cpv = int(cp)
            if cpv > 0:
                start_class_pos[i] = cpv
        except Exception:
            pass
    if start_class_pos and DEBUG:
        _log(f"Start positions captured: {len(start_class_pos)} cars")

def avg_sec(car_idx, n=None):
    """Average of the last N valid laps for car_idx (pit and incident laps excluded at recording time).
    Returns None if no valid laps."""
    all_vals = list(lap_hist.get(car_idx, []))
    if not all_vals:
        return None
    vals = all_vals[-max(1, int(n)):] if n is not None else all_vals
    return sum(vals) / len(vals)


def avg_sec_filtered(car_idx, n=None, max_over_best_pct: float = 5.0):
    """Average of recent laps while excluding slow outliers.

    A lap is ignored if it is slower than (best_lap * (1 + pct/100)), where
    best_lap is the fastest known lap for that same car (session best if
    available, otherwise fastest value in lap_hist). If fewer than `n` laps
    survive, average the available survivors.
    """
    all_vals = list(lap_hist.get(car_idx, []))
    if not all_vals:
        return None

    best = None
    try:
        best_arr = sg("CarIdxBestLapTime", []) or []
        if isinstance(best_arr, (list, tuple)) and len(best_arr) > car_idx:
            v = float(best_arr[car_idx])
            if v > 0:
                best = v
    except Exception:
        pass
    if best is None:
        try:
            best = min(float(v) for v in all_vals if float(v) > 0)
        except Exception:
            best = None

    if not best or best <= 0:
        vals = all_vals[-max(1, int(n)):] if n is not None else all_vals
        return (sum(vals) / len(vals)) if vals else None

    try:
        pct = max(0.0, float(max_over_best_pct))
    except Exception:
        pct = 5.0
    cutoff = best * (1.0 + (pct / 100.0))

    picked = []
    if n is None:
        for v in all_vals:
            try:
                fv = float(v)
            except Exception:
                continue
            if fv > 0 and fv <= cutoff:
                picked.append(fv)
    else:
        need = max(1, int(n))
        for v in reversed(all_vals):
            try:
                fv = float(v)
            except Exception:
                continue
            if fv > 0 and fv <= cutoff:
                picked.append(fv)
                if len(picked) >= need:
                    break
        picked.reverse()

    return (sum(picked) / len(picked)) if picked else None

def _init_sectors():
    """Load sector boundary pcts from SessionInfo once per session."""
    weekend = sg("WeekendInfo", {}) or {}
    track_key = (weekend.get("TrackID"), weekend.get("TrackName"), weekend.get("TrackConfigName"))
    if any(value is not None for value in track_key) and track_key != _sector_track_key[0]:
        _sector_track_key[0] = track_key
        sector_history.reset()
        _sector_pcts.clear()
        _sf_cross_time.clear()
        _sector_cross_time.clear()
        _sector_inc_at_sf.clear()
        _sector_prev_sample_t.clear()
        _prev_dp.clear()
        _sector_next_retry_t[0] = 0.0
    if sector_history.sector_numbers:
        return
    now = time.time()
    if now < _sector_next_retry_t[0]:
        return
    _sector_next_retry_t[0] = now + 5.0
    try:
        si = sg("SessionInfo", {}) or {}
        # SDK YAML exposes SplitTimeInfo at the root. Retain compatibility
        # with captures which nest it inside SessionInfo.
        split = sg("SplitTimeInfo", None) or (si.get("SplitTimeInfo") if isinstance(si, dict) else None) or {}
        sectors = split.get("Sectors") or []
        starts = {}
        for index, sec in enumerate(sectors):
            if isinstance(sec, dict):
                v = sec.get("SectorStartPct")
                if v is not None:
                    try:
                        fv = float(v)
                        number = int(sec.get("SectorNum", index))
                        if math.isfinite(fv) and 0.0 <= fv < 1.0 and number >= 0:
                            starts.setdefault(fv, number + 1)
                    except Exception:
                        pass
        pcts = sorted(pct for pct in starts if pct > 0)
        if starts and len(set(starts.values())) == len(starts):
            _sector_pcts[:] = pcts
            sector_history.configure_sectors([starts.get(0.0)] + [starts[pct] for pct in pcts])
            _sector_missing_logged[0] = False
            if DEBUG:
                _log(f"Sectors loaded: {_sector_pcts}")
        elif DEBUG and not _sector_missing_logged[0]:
            _log("_init_sectors: no sector boundaries found in SessionInfo")
            _sector_missing_logged[0] = True
    except Exception as e:
        _log(f"_init_sectors error: {e!r}")


def _est_lap_time_for_player():
    pi = player_idx()
    lastlt = sg("CarIdxLastLapTime", [])
    bestlt = sg("CarIdxBestLapTime", [])
    try:
        if lastlt and len(lastlt) > pi:
            v = float(lastlt[pi])
            if v and v > 0:
                return v
    except Exception:
        pass
    try:
        if bestlt and len(bestlt) > pi:
            v = float(bestlt[pi])
            if v and v > 0:
                return v
    except Exception:
        pass
    return None

def decode_penalty(idx: int):
    if idx == player_idx():
        pen = sg("PlayerCarBlackFlag", 0)
        try:
            pen = int(pen)
        except Exception:
            return ""

        mapping = {
            1: "DT",
            2: "SGO",
            3: "DQ",
            4: "INC",
            6: "JUMP",
            7: "PITL",
            8: "SLOW",
        }
        return mapping.get(pen, "")

    flags = sg("CarIdxSessionFlags", [])
    if flags and len(flags) > idx:
        try:
            if int(flags[idx]) & 0x00010000:
                return "BLK"
        except Exception:
            pass

    return ""


def pos_gain(car_idx, current_class_pos):
    # Prefer qualify finishing position as the reference (persists into race).
    # Fall back to session-start snapshot (start_class_pos) when no qualify data exists.
    #
    # Display format: "^N" for positions GAINED (moved up the order),
    #                 "vN" for positions LOST (moved down),
    #                 "0"  if no change.
    # Colour: green for gain, red for loss, white for no change.
    ref_pos = _qualify_class_pos.get(car_idx) or start_class_pos.get(car_idx)
    if ref_pos is None:
        return "", CLR_WHITE
    try:
        start = int(ref_pos)
        curr = int(current_class_pos)
    except Exception:
        return "", CLR_WHITE
    if curr <= 0:
        return "", CLR_WHITE
    gain = start - curr
    if gain == 0:
        return "0", CLR_WHITE
    n = abs(gain)
    if gain > 0:
        return f"^{n}", CLR_GREEN
    return f"v{n}", CLR_RED

# =============================
# SESSION DEBUG STATE (required by main.py)
# =============================

_SESSION_SIG = [None]
_LAST_SNAP_T = [0.0]
_STATE_TICK_T = [0.0]  # 261001_CURSOR
# Track SessionTick for backward-jump detection (new session = fresh tick counter)
_LAST_SESSION_TICK = [0]
# Track SubSessionID / SessionUniqueID from telemetry for extra-robust change detection
_LAST_SUBSESSION_IDS = [(None, None)]  # (WeekendInfo.SubSessionID, SessionUniqueID)
# Monotonically increasing epoch — bumped on EVERY reset event (sig change or
# tick-backward jump). Widgets compare their cached epoch against this to
# detect resets robustly, even when the signature tuple is slow to populate.
_RESET_EPOCH = [0]
# Track ir.is_connected transitions and live SessionUniqueID — both fire a
# session reset independent of the YAML-based signature tuple. iRacing keeps
# the same shared-memory layout across in-app session transitions, but the
# uid bumps and the connection state flips on a full app/test-screen cycle.
_LAST_CONNECTED = [False]
_LAST_UID = [None]
# Hash of DriverInfo's current driver lineup (set of (CarIdx, UserName)
# tuples). Fires a reset when the cars in the world change — this is the
# strongest "the YAML actually refreshed" signal we can get, because every
# other field (uid/sn/track) can lag a couple seconds behind the actual
# driver list refresh after iRacing loads a new session.
_LAST_DRIVER_HASH = [None]
_LAST_DRIVERS = [None]   # set of CarIdx for change-magnitude comparison

# Wall-clock time of the last reset that fired a destructive pyirsdk
# reconnect (shutdown+startup). Subsequent resets within this cooldown
# get the soft path only — clear caches but keep the connection alive.
# Without this, multiple reset signals firing in quick succession during a
# race (e.g. a driver dropping out causes a DriverInfo hash flip → reset →
# briefly disconnect → widgets hide; reconnect → another tick recomputes
# and triggers AGAIN) create a visible flashing/unstable cycle.
_LAST_HARD_RESET_T = [0.0]
_HARD_RESET_COOLDOWN_S = 10.0
# Wall-clock time (seconds) when the last reset epoch fired. Widgets read
# this via `is_in_reset_grace()` to decide whether to render a "RESETTING"
# placeholder while the SDK's YAML repopulates with the new session's data.
# Without this, after a reset the widgets clear cached state but immediately
# repaint using telemetry that pyirsdk hasn't refreshed yet — making it look
# like the previous session's information is still there.
_LAST_RESET_T = [0.0]
# Also track session_time so we can detect a "session_time jumped to a low
# value" event (very strong signal of a session change — joinable session
# starts the clock near 0 even if SessionUniqueID lags).
_LAST_SESS_T = [0.0]


def is_in_reset_grace(grace_seconds: float = 6.0) -> bool:
    """Returns True for `grace_seconds` after the most recent session reset.
    Widgets use this to render a placeholder instead of stale data.

    Default extended to 6s (was 3s) because pyirsdk's YAML cache can take
    several seconds to refresh DriverInfo after a session transition. With
    the shorter window, widgets would clear placeholder and immediately
    render the OLD driver list because that's still what was in YAML."""
    if _LAST_RESET_T[0] <= 0:
        return False
    try:
        return (time.time() - _LAST_RESET_T[0]) < float(grace_seconds)
    except Exception:
        return False

_CAPTURE_BUFFER = []
_FULL_CAPTURE = {
    "block_start_t": time.time(),
    "last_sample_t": 0.0,
}
_CAPTURE_SAMPLE_SECONDS = 0.5
_CAPTURE_BLOCK_SECONDS = 15.0

# Most recent per-widget "displayed" payload. Widgets pass their rendered state
# via update_state_and_debug_dump(extra={widget_name: payload}); we merge it
# here (per-key) so each capture snapshot can include what the overlay ACTUALLY
# showed on screen at that moment — not just the raw SDK telemetry. Cleared on
# every session reset so stale widget output from a previous session can't
# leak into fresh captures.
_LAST_WIDGET_EXTRAS = {}


# Estimated-time profile cache, keyed by car model. CarIdxEstTime is already
# iRacing's expected elapsed time at a track position, but values from two
# classes live in different lap-time domains. For cross-class Relative rows
# we cache the PLAYER car model around the circuit and evaluate the opponent's
# position on that one clock (the same approach used by BO2's Relative module).
#
# Each bucket retains the exact sampled position. Returning a bucket's last
# value directly creates visible steps and can be tens of metres wrong on long
# tracks. Ten-metre buckets follow irdashies' current track-length-scaled
# spacing; interpolation between exact samples follows BO2's high-precision
# cache. Profiles survive practice/qualifying/race transitions on the same
# track so the race can reuse the map already learned earlier in the event.
_EST_PROFILE_TARGET_METERS = 10.0
_EST_PROFILE_FALLBACK_BUCKETS = 400
_EST_PROFILE_MAX_SEARCH_BUCKETS = 12
_EST_PROFILE_TRACK_KEY = [None]
_EST_PROFILE_BUCKETS = [_EST_PROFILE_FALLBACK_BUCKETS]
_EST_TIME_PROFILES = defaultdict(dict)


def _est_profile_key(driver):
    if not isinstance(driver, dict):
        return ""
    return str(
        driver.get("CarPath")
        or driver.get("CarID")
        or driver.get("CarClassID")
        or ""
    )


def _est_profile_track_config():
    weekend = sg("WeekendInfo", None) or {}
    raw_length = str(weekend.get("TrackLength", "") or "").strip()
    length_m = 0.0
    try:
        parts = raw_length.lower().split()
        value = float(parts[0])
        unit = parts[1] if len(parts) > 1 else "m"
        if unit.startswith("km"):
            length_m = value * 1000.0
        elif unit.startswith("mi"):
            length_m = value * 1609.344
        else:
            length_m = value
    except Exception:
        length_m = 0.0

    track_identity = weekend.get("TrackID") or weekend.get("TrackName") or ""
    previous_key = _EST_PROFILE_TRACK_KEY[0]
    if not track_identity and length_m <= 0.0:
        return max(1, int(_EST_PROFILE_BUCKETS[0]))
    if (
        length_m <= 0.0
        and previous_key is not None
        and track_identity == previous_key[0]
    ):
        return max(1, int(_EST_PROFILE_BUCKETS[0]))

    if length_m > 0.0:
        bucket_count = max(1, int(math.ceil(
            length_m / _EST_PROFILE_TARGET_METERS
        )))
    else:
        bucket_count = _EST_PROFILE_FALLBACK_BUCKETS

    track_key = (
        track_identity,
        round(length_m, 1),
    )
    if previous_key is not None and track_key != previous_key:
        _EST_TIME_PROFILES.clear()
    _EST_PROFILE_TRACK_KEY[0] = track_key
    _EST_PROFILE_BUCKETS[0] = bucket_count
    return bucket_count


def _update_est_time_profiles(drivers, track_pcts, est_times):
    if not isinstance(track_pcts, (list, tuple)):
        return
    if not isinstance(est_times, (list, tuple)):
        return
    bucket_count = _est_profile_track_config()
    for car_idx, driver in (drivers or {}).items():
        try:
            pct = float(track_pcts[car_idx])
            est = float(est_times[car_idx])
            lap_time = float(driver.get("CarClassEstLapTime", 0) or 0)
            if not (
                math.isfinite(pct)
                and math.isfinite(est)
                and math.isfinite(lap_time)
                and 0.0 <= pct < 1.0
                and est > 0.0
                and lap_time > 0.0
                and est < lap_time * 1.25
            ):
                continue
            model_key = _est_profile_key(driver)
            if not model_key:
                continue
            bucket = min(bucket_count - 1, int(pct * bucket_count))
            _EST_TIME_PROFILES[model_key][bucket] = (pct, est)
        except Exception:
            continue


def _est_profile_at(model_key, target_pct, lap_time):
    values = _EST_TIME_PROFILES.get(model_key)
    if not values:
        return None
    try:
        target_pct = float(target_pct)
        lap_time = float(lap_time)
        if not (
            math.isfinite(target_pct)
            and math.isfinite(lap_time)
            and 0.0 <= target_pct < 1.0
            and lap_time > 0
        ):
            return None
    except Exception:
        return None

    bucket_count = max(1, int(_EST_PROFILE_BUCKETS[0]))
    target_bucket = min(bucket_count - 1, int(target_pct * bucket_count))
    lower = upper = None

    # Include the known start/finish endpoints so interpolation remains smooth
    # across the lap boundary even before those edge buckets have been sampled.
    endpoint_distance = min(target_pct, 1.0 - target_pct)
    max_distance = _EST_PROFILE_MAX_SEARCH_BUCKETS / bucket_count
    if endpoint_distance <= max_distance:
        if target_pct <= 0.5:
            lower = (0.0, 0.0)
        else:
            upper = (1.0, lap_time)

    visited = set()
    for distance in range(0, _EST_PROFILE_MAX_SEARCH_BUCKETS + 1):
        for bucket in (
            (target_bucket - distance) % bucket_count,
            (target_bucket + distance) % bucket_count,
        ):
            if bucket in visited:
                continue
            visited.add(bucket)
            entry = values.get(bucket)
            if not entry:
                continue
            try:
                sample_pct, sample_time = map(float, entry)
            except Exception:
                continue
            if not (
                math.isfinite(sample_pct)
                and math.isfinite(sample_time)
                and 0.0 <= sample_pct < 1.0
                and 0.0 < sample_time < lap_time * 1.25
            ):
                continue

            sample_x = sample_pct
            sample_y = sample_time
            if sample_x - target_pct > 0.5:
                sample_x -= 1.0
                sample_y -= lap_time
            elif sample_x - target_pct < -0.5:
                sample_x += 1.0
                sample_y += lap_time

            point = (sample_x, sample_y)
            if sample_x <= target_pct and (
                lower is None or sample_x > lower[0]
            ):
                lower = point
            if sample_x >= target_pct and (
                upper is None or sample_x < upper[0]
            ):
                upper = point

        if lower is not None and upper is not None:
            break

    if lower is None or upper is None:
        return None
    lower_pct, lower_time = lower
    upper_pct, upper_time = upper
    if abs(target_pct - lower_pct) < 1e-9:
        return lower_time % lap_time
    if abs(upper_pct - target_pct) < 1e-9:
        return upper_time % lap_time

    span = upper_pct - lower_pct
    if span <= 0:
        return None
    time_span = upper_time - lower_time
    if time_span < 0 or time_span > lap_time * 0.25:
        return None
    ratio = (target_pct - lower_pct) / span
    if not (0.0 <= ratio <= 1.0):
        return None
    return (lower_time + (upper_time - lower_time) * ratio) % lap_time


def player_est_profile_gap(player_idx, target_idx, player_pct, target_pct):
    """Cross-class short-arc gap measured on the player's car-model clock."""
    try:
        player_idx = int(player_idx)
        target_idx = int(target_idx)
        player_pct = float(player_pct)
        target_pct = float(target_pct)
    except Exception:
        return None, {}

    drivers = driver_map()
    player_driver = drivers.get(player_idx, {})
    target_driver = drivers.get(target_idx, {})
    try:
        lap_time = float(player_driver.get("CarClassEstLapTime", 0) or 0)
    except Exception:
        lap_time = 0.0
    if not (20.0 <= lap_time <= 2000.0):
        lap_time = session_best_lap(player_idx) or avg_sec(player_idx, 3) or 0.0
    if not (20.0 <= lap_time <= 2000.0):
        return None, {}

    est_times = sg("CarIdxEstTime", []) or []
    try:
        player_est = float(est_times[player_idx])
        target_est_live = float(est_times[target_idx])
    except Exception:
        return None, {}
    if player_est < 0 or target_est_live < 0:
        return None, {}

    player_key = _est_profile_key(player_driver)
    target_key = _est_profile_key(target_driver)
    source = "player_model_exact_cache"
    if player_key and player_key == target_key:
        target_in_player_frame = target_est_live
        source = "same_model_live"
    else:
        target_in_player_frame = _est_profile_at(
            player_key, target_pct, lap_time
        )

    if target_in_player_frame is None:
        try:
            target_lap_time = float(
                target_driver.get("CarClassEstLapTime", 0) or 0
            )
        except Exception:
            target_lap_time = 0.0
        if target_lap_time <= 0:
            return None, {}
        target_in_player_frame = (
            target_est_live * lap_time / target_lap_time
        )
        source = "scaled_live_fallback"

    dd_frac = (target_pct - player_pct + 0.5) % 1.0 - 0.5
    gap = float(target_in_player_frame) - player_est
    while gap < -0.5 * lap_time:
        gap += lap_time
    while gap > 0.5 * lap_time:
        gap -= lap_time

    # Convert to the signed short arc. Small profile interpolation noise near
    # an equal track position must not turn a 0.1s gap into almost a full lap.
    sign = 1.0 if dd_frac >= 0 else -1.0
    if gap * sign < 0:
        if abs(gap) <= 2.0 or abs(dd_frac) <= 0.02:
            gap = abs(gap) * sign
        else:
            gap += lap_time * sign

    linear_estimate = abs(dd_frac) * lap_time
    sanity_limit = max(3.0, linear_estimate * 3.0)
    if abs(gap) > sanity_limit or abs(gap) > lap_time * 0.75:
        return None, {
            "source": source,
            "rejected": "physical_sanity",
            "raw_gap": gap,
            "linear_estimate": linear_estimate,
            "player_lap_time": lap_time,
        }

    return gap, {
        "source": source,
        "player_est": player_est,
        "target_in_player_frame": target_in_player_frame,
        "player_lap_time": lap_time,
        "linear_estimate": linear_estimate,
        "profile_points": len(_EST_TIME_PROFILES.get(player_key, {})),
        "profile_buckets": int(_EST_PROFILE_BUCKETS[0]),
    }


# ============================================================================
# REFERENCE LAP — port of irdashies' ReferenceLapStore + relativeGapHelpers
# ============================================================================
# Faithful Python port of the irdashies project's algorithm. Three components:
#
#   1. STORE  (this module-level state)
#      - active_laps   : Map[carIdx → ReferenceLap]   currently-being-driven lap
#      - best_laps     : Map[carIdx → ReferenceLap]   per-car best clean lap
#      - persisted_laps: Map[classId → ReferenceLap]  per-class best (session-wide)
#
#   2. RECORDER  (_collect_lap_data)
#      Called every paint tick, FOR EACH driver. Adds at most one refPoint per
#      normalized track-pct key per lap. On dp wrap (>0.95 → <0.05) the lap is
#      finalized; if it has ≥ MIN_POINTS_FOR_VALID_LAP and is clean (not on pit
#      during recording), PCHIP tangents are precomputed and the lap is stored
#      as the per-car best (if faster than current best) and also as the
#      class-best in persisted_laps.
#
#   3. INTERPOLATION + DELTAS  (interpolate_at_point, calculate_reference_delta,
#      calculate_class_estimated_delta)
#      Source: src/frontend/components/Standings/interpolation.ts and
#              src/frontend/components/Standings/relativeGapHelpers.ts
#      and:    src/frontend/context/ReferenceLapStore/pchipTangents.ts
#
# Sign convention (matches irdashies calculateReferenceDelta):
#   delta = t_opponent - t_player (in BEHIND-car's pace frame), wrapped by
#   ±lap_time when track-pct difference crosses ±0.5. Positive = opp ahead.

REFERENCE_INTERVAL = 0.0025  # irdashies const — 400 keys per lap
_REF_INTERVAL_DECIMALS = 4   # len of decimal portion of 0.0025
MIN_POINTS_FOR_VALID_LAP = 400  # irdashies const

# active_laps: incomplete laps currently being recorded for each car.
# Each value is a dict matching irdashies' ReferenceLap shape:
#   { class_id, start_time, finish_time, ref_points: dict[key → point],
#     last_tracked_pct, is_clean_lap }
# where each point is { track_pct, time_elapsed_since_start, tangent }.
_REF_LAP_ACTIVE = {}
# best_laps: each car's BEST clean completed lap this session
_REF_LAP_BEST = {}
# persisted_laps: each class's best clean lap this session (any car).
# In irdashies this is loaded from disk on startup; we just track session-best
# (no disk persistence — would need a bridge layer).
_REF_LAP_PERSISTED = {}


def _normalize_key(key):
    """Port of normalizeKey from ReferenceLapStore.tsx — quantizes a track-pct
    to the nearest REFERENCE_INTERVAL grid cell. Returns 0 for out-of-range."""
    try:
        k = float(key)
    except Exception:
        return 0.0
    nk = round(k - (k % REFERENCE_INTERVAL), _REF_INTERVAL_DECIMALS)
    if nk < 0 or nk >= 1:
        return 0.0
    return nk


def _is_lap_clean(track_surface, is_on_pit_road):
    """Port of isLapClean. irdashies hardcodes trackSurface = OnTrack in the
    updater (TrackLocation.OnTrack == 3), so effectively only pit-road taints
    the lap. We follow that simplification."""
    return (track_surface == 3) and (not is_on_pit_road)


def _ref_lap_reset():
    """Port of completeSession — wipes all state. Called on session change."""
    _REF_LAP_ACTIVE.clear()
    _REF_LAP_BEST.clear()
    _REF_LAP_PERSISTED.clear()


# ---- PCHIP tangents (port of pchipTangents.ts) -----------------------------

def _compute_pchip_tangents(x, y, lap_time):
    """Port of computePCHIPTangents. Computes Fritsch-Carlson PCHIP tangents
    with wrap-around (so the curve is closed across the S/F line)."""
    n = len(x)
    if n < 2:
        return [0.0] * n
    tangents = [0.0] * n
    deltas = [0.0] * (n - 1)
    for k in range(n - 1):
        dx = x[k + 1] - x[k]
        if dx == 0:
            deltas[k] = 0.0
        else:
            deltas[k] = (y[k + 1] - y[k]) / dx

    # Wrap-around delta: previous point is at (x[n-1] - 1, y[n-1] - lap_time)
    dx_pre = x[0] - (x[n - 1] - 1)
    delta_before_first = ((y[0] - (y[n - 1] - lap_time)) / dx_pre) if dx_pre != 0 else 0.0
    # Next-after-last: at (x[0] + 1, y[0] + lap_time)
    dx_post = x[0] + 1 - x[n - 1]
    delta_after_last = ((y[0] + lap_time - y[n - 1]) / dx_post) if dx_post != 0 else 0.0

    # First point
    d_0 = delta_before_first
    d_1 = deltas[0]
    if d_0 * d_1 <= 0:
        tangents[0] = 0.0
    else:
        dx_after = x[1] - x[0]
        dx_before = x[0] - (x[n - 1] - 1)
        w1 = 2 * dx_after + dx_before
        w2 = dx_after + 2 * dx_before
        denom = (w1 / d_0 + w2 / d_1)
        tangents[0] = ((w1 + w2) / denom) if denom != 0 else 0.0

    # Last point
    d_nm2 = deltas[n - 2]
    d_nm1 = delta_after_last
    if d_nm2 * d_nm1 <= 0:
        tangents[n - 1] = 0.0
    else:
        dx_before = x[n - 1] - x[n - 2]
        dx_after = x[0] + 1 - x[n - 1]
        w1 = 2 * dx_after + dx_before
        w2 = dx_after + 2 * dx_before
        denom = (w1 / d_nm2 + w2 / d_nm1)
        tangents[n - 1] = ((w1 + w2) / denom) if denom != 0 else 0.0

    # Interior
    for k in range(1, n - 1):
        d_k = deltas[k - 1]
        d_kp1 = deltas[k]
        if d_k * d_kp1 <= 0:
            tangents[k] = 0.0
        else:
            w1 = 2 * (x[k + 1] - x[k]) + (x[k] - x[k - 1])
            w2 = (x[k + 1] - x[k]) + 2 * (x[k] - x[k - 1])
            denom = (w1 / d_k + w2 / d_kp1)
            tangents[k] = ((w1 + w2) / denom) if denom != 0 else 0.0
    return tangents


def _precompute_pchip_tangents(lap):
    """Port of precomputePCHIPTangents. Sorts the lap's refPoints by track_pct,
    computes Fritsch-Carlson tangents (with wrap-around through S/F), and
    writes each tangent back into the corresponding point dict in place."""
    points = sorted(lap["ref_points"].values(), key=lambda p: p["track_pct"])
    if len(points) < 2:
        return
    x = [p["track_pct"] for p in points]
    y = [p["time_elapsed_since_start"] for p in points]
    lap_time = lap["finish_time"] - lap["start_time"]
    tangents = _compute_pchip_tangents(x, y, lap_time)
    for i, p in enumerate(points):
        p["tangent"] = tangents[i]


# ---- Hermite/PCHIP interpolation (port of interpolation.ts) ----------------

def _hermite_basis(t, y0, y1, m0, m1):
    """Direct port of hermiteBasis from interpolation.ts."""
    t2 = t * t
    t3 = t2 * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return h00 * y0 + h10 * m0 + h01 * y1 + h11 * m1


def interpolate_at_point(lap, target_pct):
    """Port of interpolateAtPoint from interpolation.ts. O(1) lookup using the
    pre-built ref_points map. Returns None when the lap has no data near the
    target. Handles the S/F wrap when p1 falls onto the next lap."""
    if not lap or not lap.get("ref_points"):
        return None
    pts = lap["ref_points"]
    key0 = _normalize_key(target_pct)
    key1 = _normalize_key(target_pct + REFERENCE_INTERVAL)
    p0 = pts.get(key0)
    p1 = pts.get(key1)
    if not p0:
        return None
    if not p1:
        return p0["time_elapsed_since_start"]
    if p0.get("tangent") is None or p1.get("tangent") is None:
        return None

    h = p1["track_pct"] - p0["track_pct"]
    y1 = p1["time_elapsed_since_start"]
    if h <= 0:
        # wrap-around the finish line
        h = 1 - p0["track_pct"] + p1["track_pct"]
        lap_time = lap["finish_time"] - lap["start_time"]
        y1 = p1["time_elapsed_since_start"] + lap_time
    if h <= 0:
        return p0["time_elapsed_since_start"]

    t = (target_pct - p0["track_pct"]) / h
    # Defense: PCHIP extrapolation (|t| ≫ 1) can produce absurd values when
    # the stored track_pcts cluster very close together (h tiny) but the
    # query target falls far outside [p0, p1]. Real cause: an out-of-trend
    # sample (e.g. car came back through this bucket much later in the lap
    # after an off) pollutes one bucket. irdashies has this latent — they
    # don't dirty laps on off-track. Linear extrapolation is also unsafe
    # because the polluted point's y is far off the trend, so we CLAMP t
    # to [0, 1] — falls back to one of the bracket points' times.
    if t < 0.0:
        return p0["time_elapsed_since_start"]
    if t > 1.0:
        return y1

    return _hermite_basis(
        t,
        p0["time_elapsed_since_start"],
        y1,
        p0["tangent"] * h,
        p1["tangent"] * h,
    )


# ---- Recorder (port of collectLapData) -------------------------------------

def _collect_lap_data(car_idx, class_id, track_pct, session_time,
                     track_surface, is_on_pit_road, is_yellow=False):
    """Direct port of ReferenceLapStore.collectLapData. Mutates _REF_LAP_ACTIVE
    in place. On lap completion, promotes a clean fast lap to best_laps and
    persisted_laps.

    The lap is marked DIRTY (is_clean_lap=False) when:
      - is_on_pit_road is True at any point during the lap, OR
      - is_yellow is True at any point during the lap (NEW — caution-flag
        laps run at pace-car speed, ~3x normal lap time. Recording them
        as the reference makes Relative INT 3x too long for cross-car
        gaps. Verified via relative_reports_20260508.jsonl: Indy oval
        flagged 1.18s INT for a 0.95% gap; with caution-contaminated ref
        lap of ~120s instead of 40s, that's exactly 1.18s instead of the
        correct 0.38s. Caution detection bumped is_clean_lap to False so
        the lap is rejected as the reference.)
      - The committed lap_time is unrealistically long vs the car's
        own CarIdxBestLapTime / class median (NEW — defence in depth
        for cases where SessionFlags isn't reporting yellow correctly,
        like local-yellow zones).
    """
    if track_pct is None or track_pct < 0:
        return
    ref_lap = _REF_LAP_ACTIVE.get(car_idx)
    key = _normalize_key(track_pct)

    # First sample for this car — initialize an active lap.
    if not ref_lap:
        _REF_LAP_ACTIVE[car_idx] = {
            "class_id": class_id,
            "start_time": session_time,
            "finish_time": -1,
            "ref_points": {
                key: {
                    "track_pct": float(track_pct),
                    "time_elapsed_since_start": 0.0,
                    "tangent": None,
                }
            },
            "last_tracked_pct": float(track_pct),
            "is_clean_lap": _is_lap_clean(track_surface, is_on_pit_road) and not is_yellow,
        }
        return

    is_lap_complete = (ref_lap["last_tracked_pct"] > 0.95) and (track_pct < 0.05)

    if is_lap_complete:
        ref_lap["finish_time"] = session_time
        current_lap_time = ref_lap["finish_time"] - ref_lap["start_time"]

        # Speed sanity check — reject obvious caution / pit-out / formation
        # laps that slipped through the yellow-flag detection. Compare the
        # committed lap to:
        #   - the car's own CarIdxBestLapTime (the gold standard)
        #   - else the active best_lap we already have for this car
        # If the new lap is >40% slower than either, treat as not-clean.
        # Threshold chosen from real data: caution laps at Indy oval are
        # ~3x normal lap time, road-course caution ~1.5-2x. 1.4x catches
        # both while permitting normal lap-time variance (slipstream,
        # weather, slight off-track).
        try:
            _bestlt_arr = sg("CarIdxBestLapTime", []) or []
            ref_best = None
            if isinstance(_bestlt_arr, (list, tuple)) and car_idx < len(_bestlt_arr):
                _v = float(_bestlt_arr[car_idx])
                if _v > 20:
                    ref_best = _v
            if ref_best is None:
                _existing = _REF_LAP_BEST.get(car_idx)
                if _existing:
                    ref_best = _existing["finish_time"] - _existing["start_time"]
            if ref_best and ref_best > 0 and current_lap_time > ref_best * 1.4:
                ref_lap["is_clean_lap"] = False
        except Exception:
            pass

        if (len(ref_lap["ref_points"]) >= MIN_POINTS_FOR_VALID_LAP
                and current_lap_time > 0):
            best_lap = _REF_LAP_BEST.get(car_idx)
            if best_lap:
                is_new_best = current_lap_time < (best_lap["finish_time"] - best_lap["start_time"])
            else:
                is_new_best = True

            if is_new_best and ref_lap["is_clean_lap"]:
                _precompute_pchip_tangents(ref_lap)
                _REF_LAP_BEST[car_idx] = ref_lap

                saved_lap = _REF_LAP_PERSISTED.get(ref_lap["class_id"])
                saved_lap_time = (
                    saved_lap["finish_time"] - saved_lap["start_time"]
                    if saved_lap else float("inf")
                )
                if current_lap_time < saved_lap_time:
                    _REF_LAP_PERSISTED[ref_lap["class_id"]] = ref_lap

        # Reset active lap for the new lap (which started at this S/F crossing).
        _REF_LAP_ACTIVE[car_idx] = {
            "class_id": class_id,
            "start_time": session_time,
            "finish_time": -1,
            "ref_points": {
                key: {
                    "track_pct": float(track_pct),
                    "time_elapsed_since_start": 0.0,
                    "tangent": None,
                }
            },
            "last_tracked_pct": float(track_pct),
            "is_clean_lap": _is_lap_clean(track_surface, is_on_pit_road) and not is_yellow,
        }
        return

    # Still mid-lap: dirty the lap if pit-road OR yellow flag flying.
    if ref_lap["is_clean_lap"] and (is_on_pit_road or is_yellow):
        ref_lap["is_clean_lap"] = False

    # Add a new refPoint only if (a) the key isn't already filled and (b) the
    # lap is still clean (no points after pit entry / yellow flag).
    if (key not in ref_lap["ref_points"]) and ref_lap["is_clean_lap"]:
        ref_lap["ref_points"][key] = {
            "track_pct": float(track_pct),
            "time_elapsed_since_start": session_time - ref_lap["start_time"],
            "tangent": None,
        }
    # Always advance the wrap detector, including dirty laps. Previously a
    # pit/caution froze this value at the dirty point, so the next S/F wrap
    # was never seen and this car's reference recorder stayed dirty forever.
    ref_lap["last_tracked_pct"] = float(track_pct)


# ---- Public API ------------------------------------------------------------

def get_reference_lap(car_idx, class_id, use_persistence):
    """Port of getReferenceLap. Used by callers (e.g. relative.py) to fetch
    the right reference lap for delta computation:

    - use_persistence=True  → return the class-level best (used when the car
                              is on its starting lap and has no per-car ref).
    - use_persistence=False → return the car's per-session best, or fall back
                              to the class-level if no per-car best exists.

    Always returns a ReferenceLap dict (possibly empty refPoints if neither
    persistence nor a best is available, with finish_time = -1 to signal
    "no data" to downstream callers).
    """
    best_lap = _REF_LAP_BEST.get(car_idx)
    if use_persistence or not best_lap:
        persisted = _REF_LAP_PERSISTED.get(class_id)
        if persisted:
            return persisted
        return {
            "class_id": class_id,
            "start_time": -1,
            "finish_time": -1,
            "ref_points": {},
            "last_tracked_pct": -1,
            "is_clean_lap": False,
        }
    return best_lap


def calculate_reference_delta(reference_lap, opponent_track_pct, player_track_pct):
    """Direct port of calculateReferenceDelta from relativeGapHelpers.ts.
    Returns the signed time gap (opp − player) in the BEHIND-car's pace
    frame (since the caller passes the BEHIND car's reference lap), wrapped
    by ±lap_time when the track-pct difference crosses ±0.5."""
    t_player = interpolate_at_point(reference_lap, player_track_pct)
    if t_player is None:
        t_player = 0.0
    t_opp = interpolate_at_point(reference_lap, opponent_track_pct)
    if t_opp is None:
        t_opp = 0.0

    delta = t_opp - t_player
    lap_time = reference_lap["finish_time"] - reference_lap["start_time"]
    track_pct_diff = opponent_track_pct - player_track_pct

    if track_pct_diff <= -0.5:
        delta += lap_time
    elif track_pct_diff >= 0.5:
        delta -= lap_time

    return delta


def calculate_class_estimated_delta(ahead_est_time, ahead_class_est_time,
                                    behind_est_time, behind_class_est_time,
                                    is_target_ahead):
    """Direct port of calculateClassEstimatedDelta from relativeGapHelpers.ts.
    Used as the fallback when no reference lap is available or someone is on
    pit road. The reference (ruler) is ALWAYS the BEHIND car; we scale the
    AHEAD car's est into the BEHIND car's class units. Sign:
        is_target_ahead=True  → positive = target is ahead (opp ahead of player)
        is_target_ahead=False → negative = target is behind (opp behind player)
    """
    if ahead_class_est_time <= 0:
        return 0.0
    scaling_ratio = behind_class_est_time / ahead_class_est_time
    ahead_scaled = ahead_est_time * scaling_ratio
    ref_lap_time = behind_class_est_time

    if is_target_ahead:
        delta = ahead_scaled - behind_est_time
        if delta < -ref_lap_time / 2:
            delta += ref_lap_time
    else:
        delta = behind_est_time - ahead_scaled
        if delta > ref_lap_time / 2:
            delta -= ref_lap_time
    return delta


def ref_lap_ready_for(car_idx, class_id, use_persistence):
    """Convenience: True iff get_reference_lap returns a usable lap."""
    lap = get_reference_lap(car_idx, class_id, use_persistence)
    return bool(lap and lap.get("finish_time", -1) > 0
                and lap.get("ref_points")
                and len(lap["ref_points"]) >= MIN_POINTS_FOR_VALID_LAP)

def _session_signature():
    # NOTE: SessionState intentionally excluded — it changes within a race
    # (warmup→racing→checkered→cooldown) and must NOT trigger a lap-history reset.
    #
    # Signature includes multiple redundant fields so ANY real session transition
    # fires the reset, even if one of the IDs is slow to update in shared memory:
    #   - WeekendInfo.SessionID     (iRacing SubSessionID, unique per event)
    #   - WeekendInfo.SubSessionID  (older key name, kept as extra signal)
    #   - SessionUniqueID           (from telemetry directly, not YAML)
    #   - SessionNum                (practice/qualify/race index within event)
    #   - SessionType               (string: "Race", "Qualifying", "Practice")
    #   - WeekendInfo.TrackName     (catches event changes)
    try:
        wi = sg("WeekendInfo", None) or {}
    except Exception:
        wi = {}
    try:
        tid = wi.get("TrackName")
    except Exception:
        tid = None
    try:
        sid = wi.get("SessionID")
    except Exception:
        sid = None
    try:
        sub = wi.get("SubSessionID")
    except Exception:
        sub = None
    try:
        uid = sg("SessionUniqueID", None)
    except Exception:
        uid = None
    try:
        sn = sg("SessionNum", None)
    except Exception:
        sn = None
    st = None
    try:
        si = sg("SessionInfo", None) or {}
        sessions = si.get("Sessions") if isinstance(si, dict) else None
        sn_i = int(sn) if sn is not None else None
        if isinstance(sessions, list) and sn_i is not None and 0 <= sn_i < len(sessions):
            st = (sessions[sn_i] or {}).get("SessionType")
    except Exception:
        st = None
    if not st:
        try:
            st = sg("SessionType", None)
        except Exception:
            st = None
    return (sid, sub, uid, sn, st, tid)

DB_FILE = os.path.join(BASE_DIR, "database.json")


def _db_load():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _db_save(db: dict):
    try:
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, DB_FILE)
    except Exception:
        pass


_DB = {"t": 0.0, "data": None}


def db_get():
    if _DB["data"] is None:
        _DB["data"] = _db_load()
    return _DB["data"]

def db_flush(force=False):
    t = time.time()
    if force or (t - float(_DB["t"] or 0.0) >= 0.25):
        _db_save(db_get())
        _DB["t"] = t


def db_car_key(drv: dict, car_idx: int):
    # try:
    #     num = str(drv.get("CarNumber", "")).strip()
    # except Exception:
    #     num = ""
    # return f"idx:{int(car_idx)}|num:{num}"
    uid = normalize_user_id(drv.get("UserID")) if isinstance(drv, dict) else None  # 261001_CURSOR
    if uid is not None:  # 261001_CURSOR
        return f"id:{uid}"  # 261001_CURSOR
    try:  # 261001_CURSOR
        num = str(drv.get("CarNumber", "")).strip()  # 261001_CURSOR
    except Exception:  # 261001_CURSOR
        num = ""  # 261001_CURSOR
    return f"idx:{int(car_idx)}|num:{num}"  # 261001_CURSOR


def db_set_car_field(drv: dict, car_idx: int, field: str, value):
    db = db_get()
    cars = db.setdefault("cars", {})
    k = db_car_key(drv, car_idx)
    c = cars.setdefault(k, {})
    if value is None or value == "":
        return
    c[field] = value
    c["_ts"] = time.time()
    db_flush()


def db_get_car_field(drv: dict, car_idx: int, field: str, default=""):
    try:
        cars = db_get().get("cars") or {}
        k = db_car_key(drv, car_idx)
        c = cars.get(k) or {}
        v = c.get(field, default)
        return default if v is None else v
    except Exception:
        return default


def ir_short(prefix, ir):
    try:
        v = int(float(ir))
    except Exception:
        return ""
    if v >= 10000:
        return f"{v//1000}k"
    if v >= 1000:
        return f"{v/1000.0:.1f}k"
    return str(v)

def sr_color_from_lic(drv: dict):
    try:
        lic = str(drv.get("LicString", "")).strip()
    except Exception:
        return CLR_WHITE
    if not lic:
        return CLR_WHITE
    grade = lic[0].upper()
    return {
        "A": QColor(0, 120, 255),    # blue
        "B": QColor(0, 200, 0),      # green
        "C": QColor(255, 220, 0),    # yellow
        "D": QColor(255, 140, 0),    # orange
    }.get(grade, CLR_WHITE)

def _get_list_var(name: str):
    v = sg(name, None)
    return v if isinstance(v, (list, tuple)) else None


def incidents_for_car(car_idx: int, drv: dict, team_inc: int, cur_inc_var):
    try:
        ci = sg("CarIdxIncidentCount", None)
        if isinstance(ci, (list, tuple)) and len(ci) > car_idx:
            v = int(float(ci[car_idx]))
            db_set_car_field(drv, car_idx, "inc", str(v))
            return str(v) if v > 0 else ""
    except Exception:
        pass

    return db_get_car_field(drv, car_idx, "inc", "")


def _flags_blackflag(flags_int: int) -> bool:
    # keep your old bit, plus common variants used by overlays
    return bool(flags_int & 0x00010000) or bool(flags_int & 0x00000002) or bool(flags_int & 0x00000004)

def penalty_text_for_car(car_idx: int, drv: dict):
    if car_idx == player_idx():
        pen = sg("PlayerCarBlackFlag", 0)
        try:
            pen = int(pen)
        except Exception:
            pen = 0
        mapping = {1: "DT", 2: "SGO", 3: "DQ", 4: "INC", 6: "JUMP", 7: "PITL", 8: "SLOW"}
        txt = mapping.get(pen, "")
        if txt:
            db_set_car_field(drv, car_idx, "pen", txt)
        return txt or db_get_car_field(drv, car_idx, "pen", "")

    flags = sg("CarIdxSessionFlags", [])
    if isinstance(flags, (list, tuple)) and len(flags) > car_idx:
        try:
            fi = int(flags[car_idx])
            txt = "BLK" if _flags_blackflag(fi) else ""
            if txt:
                db_set_car_field(drv, car_idx, "pen", txt)
                return txt
        except Exception:
            pass

    cached = db_get_car_field(drv, car_idx, "pen", "")
    return cached or ""


def update_state_and_debug_dump(extra: dict = None):
    global DATA_FILE
    # Merge per-widget "displayed" payload into the shared buffer so full-capture
    # snapshots can record what the overlay rendered, not just raw SDK values.
    # Keyed by widget name (fuel/relative/standings/info/input) — each call
    # overwrites just its own key, leaving the others intact. This is the input
    # the capture_inspect reader uses to compare "what we showed" vs raw truth.
    if extra:
        try:
            for _k, _v in extra.items():
                _LAST_WIDGET_EXTRAS[_k] = _v
        except Exception:
            pass

    now_tick = time.monotonic()  # 261001_CURSOR
    if now_tick - _STATE_TICK_T[0] < 0.05:  # 261001_CURSOR
        return  # 261001_CURSOR
    _STATE_TICK_T[0] = now_tick  # 261001_CURSOR

    sig = _session_signature()

    # ---- Extra reset triggers besides the signature tuple ----
    # Some transitions (especially joining a new session with the overlay open)
    # are slow to update the YAML-based WeekendInfo fields in shared memory, so
    # a new session can be underway for several seconds before the tuple flips.
    # We also watch the live SessionTick counter — it resets to a small value
    # when iRacing loads a new session, so any backward jump is a strong signal.
    _force_reset = False
    try:
        _cur_tick = int(sg("SessionTick", 0) or 0)
        # A big backward jump (>100 ticks, ~1.7s at 60Hz) implies a new session
        # loaded. Forward jumps are normal; tiny backward jitter we ignore.
        if _cur_tick > 0 and _LAST_SESSION_TICK[0] > 0 and _cur_tick < _LAST_SESSION_TICK[0] - 100:
            _force_reset = True
            if DEBUG:
                _log(f"Session reset: SessionTick jumped backward {_LAST_SESSION_TICK[0]} → {_cur_tick}")
        _LAST_SESSION_TICK[0] = _cur_tick
    except Exception:
        pass

    # Disconnect → reconnect transition: when the user leaves iRacing entirely
    # (back to the test/launch screen) and joins another session, ir.is_connected
    # flips False then True. The YAML signature can take several seconds to
    # repopulate after that, so without this we'd render last-session data first.
    _conn_just_returned = False
    try:
        cur_conn = bool(getattr(ir, "is_connected", False))
        if cur_conn and not _LAST_CONNECTED[0]:
            _force_reset = True
            _conn_just_returned = True   # eligible for hard reconnect
            if DEBUG:
                _log("Session reset: iRacing reconnected")
        _LAST_CONNECTED[0] = cur_conn
    except Exception:
        pass

    # Direct SessionUniqueID watch: bumps each new session even if the YAML
    # signature is stale. Independent of _session_signature() to give us the
    # earliest possible reset signal.
    _uid_changed = False
    try:
        _cur_uid = sg("SessionUniqueID", None)
        if _cur_uid is not None and _LAST_UID[0] is not None and _cur_uid != _LAST_UID[0]:
            _force_reset = True
            _uid_changed = True           # eligible for hard reconnect
            if DEBUG:
                _log(f"Session reset: SessionUniqueID {_LAST_UID[0]} → {_cur_uid}")
        _LAST_UID[0] = _cur_uid
    except Exception:
        pass

    # SessionTime backward jump: a new session starts the clock near 0. If we
    # see a substantial drop (>30 seconds back) from the previous tick's value,
    # it's a definite session change.
    try:
        _cur_sess_t = float(sg("SessionTime", 0.0) or 0.0)
        if (_cur_sess_t > 0 and _LAST_SESS_T[0] > 60
                and _cur_sess_t < _LAST_SESS_T[0] - 30):
            _force_reset = True
            if DEBUG:
                _log(f"Session reset: SessionTime jumped backward "
                     f"{_LAST_SESS_T[0]:.0f} → {_cur_sess_t:.0f}")
        _LAST_SESS_T[0] = _cur_sess_t
    except Exception:
        pass

    # DriverInfo lineup change — only fire when a SUBSTANTIAL fraction of
    # drivers are new. A single driver disconnecting/reconnecting in a race
    # also flips the hash but should NOT trigger a session reset (it caused
    # constant flashing during races). We require that at least 25% of the
    # CarIdx set is new compared to the previous lineup, OR the lineup size
    # changed by >= 4 — both signals of a true session transition.
    try:
        di = sg("DriverInfo", None) or {}
        drivers = di.get("Drivers") or []
        if isinstance(drivers, list):
            cur_idxs = set()
            for d in drivers:
                if not isinstance(d, dict):
                    continue
                ci = d.get("CarIdx")
                if ci is not None:
                    try:
                        cur_idxs.add(int(ci))
                    except Exception:
                        pass
            if cur_idxs:
                prev_idxs = _LAST_DRIVERS[0]
                if prev_idxs is not None and prev_idxs:
                    diff = cur_idxs.symmetric_difference(prev_idxs)
                    pct_changed = len(diff) / max(len(prev_idxs), len(cur_idxs))
                    size_change = abs(len(cur_idxs) - len(prev_idxs))
                    if pct_changed >= 0.25 or size_change >= 4:
                        _force_reset = True
                        if DEBUG:
                            _log(f"Session reset: DriverInfo lineup changed "
                                 f"({len(prev_idxs)}→{len(cur_idxs)} cars, "
                                 f"{int(pct_changed*100)}% diff)")
                _LAST_DRIVERS[0] = cur_idxs
    except Exception:
        pass

    if sig != _SESSION_SIG[0] or _force_reset:
        # New practice / qualify / race detected — reset all per-session state.
        # start_class_pos is cleared here and re-read by init_start_positions() on the
        # very next paintEvent, capturing fresh grid/starting positions for the P column.
        # _qualify_class_pos is intentionally NOT cleared here — it persists across
        # sessions within the same event so the race P column shows movement vs qualify.
        if DEBUG:
            _log(f"Session reset: {_SESSION_SIG[0]} → {sig}  force={_force_reset}")
        _SESSION_SIG[0] = sig
        _RESET_EPOCH[0] += 1  # signal widgets to clear their internal state
        _LAST_RESET_T[0] = time.time()  # start the reset-grace window
        # Clear the driver hash so the next DriverInfo-change detection is
        # fresh — this prevents stale-hash-vs-stale-hash matching from
        # suppressing a legitimate second-stage reset when YAML lags.
        _LAST_DRIVER_HASH[0] = None

        # ---- pyirsdk YAML cache: counter-only invalidation (SAFE) ----
        # Why this is needed: between sessions, pyirsdk's natural lazy-parse
        # waits for iRacing's session_info_update counter to bump. In
        # practice (verified data_20260511_182402.json across three
        # consecutive uid transitions), the counter can lag 30+ seconds
        # behind the actual YAML rotation — so driver_map() returns the
        # OLD session's drivers (or empty) for that whole window and
        # standings/relative widgets show nothing.
        #
        # Setting `last_session_info_update = -1` forces pyirsdk's NEXT
        # `_get_yaml_value` call to consider the cache stale and re-parse
        # the shared-memory buffer immediately. We do NOT null the
        # parsed dict (`_IRSDK__session_info_dict`) — that previously
        # caused permanent breakage when re-parse returned an empty dict
        # at the exact moment of the transition (the dict stayed None
        # forever because the empty-result is stored back). Leaving the
        # dict in place means: if re-parse returns valid new YAML, dict
        # updates; if re-parse returns empty, dict retains OLD valid
        # data so widgets keep working with slightly-stale-but-valid
        # rows until the next successful parse.
        try:
            ir.last_session_info_update = -1
        except Exception:
            pass
        # A car/session transition can reorder iRacing's variable-header table
        # without closing shared memory. Refresh pyirsdk's cached name map now,
        # before any widget can carry old offsets into the new session.
        _refresh_telemetry_layout("session reset")
        _ = (_uid_changed, _conn_just_returned, _HARD_RESET_COOLDOWN_S)
        _LAST_SNAP_T[0] = 0.0
        start_class_pos.clear()
        pit_entry_time.clear()
        last_pit_lap_completed.clear()
        prev_on_pit.clear()
        reset_lap_history()
        _pit_laps.clear()
        _last_pit_lap.clear()
        _prev_pit_state.clear()
        _inc_cache.clear()
        _inc_prev_raw.clear()
        _inc_surf_prev.clear()
        _inc_offtrack_t.clear()
        _inc_offtrack_until.clear()
        _inc_dp_hist.clear()
        _inc_stopped_until.clear()
        _inc_stopped_at.clear()
        _inc_crash_until.clear()
        _inc_stop_score.clear()
        _sf_cross_time.clear()
        _sector_cross_time.clear()
        _sector_pcts.clear()   # force reload for new track/session
        _sector_next_retry_t[0] = 0.0
        _sector_missing_logged[0] = False
        sector_history.reset()
        _sector_inc_at_sf.clear()
        _sector_prev_sample_t.clear()
        _sector_track_key[0] = None
        _prev_dp.clear()
        _session_best_lap_sec.clear()
        _session_all_laps_sec.clear()
        # EstTime car-model profiles are track data, not session data. Keeping
        # them lets Race reuse the complete map learned in Practice/Qualifying;
        # _est_profile_track_config clears them when the track changes.
        _LAST_WIDGET_EXTRAS.clear()  # don't leak prev-session displayed state into new captures
        if DEBUG and _CAPTURE_BUFFER:
            try:
                _append_jsonl({
                    "tag": "block",
                    "schema": 2,
                    "start": _FULL_CAPTURE["block_start_t"],
                    "end": time.time(),
                    "meta": _collect_capture_metadata(),
                    "samples": _CAPTURE_BUFFER,
                })
            except Exception:
                pass
        _CAPTURE_BUFFER.clear()      # don't mix old/new sessions in the same capture block
        _FULL_CAPTURE["block_start_t"] = time.time()
        _FULL_CAPTURE["last_sample_t"] = 0.0
        _ref_lap_reset()             # wipe player's reference lap on new session
        if DEBUG:
            # One debug file per detected session reset; avoids appending a new
            # session into an older file and keeps offline analysis clean.
            try:
                _sn = sig[3] if len(sig) > 3 else None
                _st = str(sig[4] if len(sig) > 4 else "") or ""
                _st = "".join(ch for ch in _st.lower() if ch.isalnum())[:16]
                _uid = sig[2] if len(sig) > 2 else None
                _epoch = int(_RESET_EPOCH[0])
                _name = f"data_{time.strftime('%Y%m%d_%H%M%S')}_e{_epoch}"
                if _sn is not None:
                    _name += f"_s{_sn}"
                if _st:
                    _name += f"_{_st}"
                if _uid is not None:
                    _name += f"_u{_uid}"
                DATA_FILE = os.path.join(DEBUG_ARCHIVE_DIR, _name + ".json")
                _reset_jsonl_file()
                _log(f"Debug capture file rotated on session reset: {DATA_FILE}")
            except Exception as _rot_ex:
                _log(f"debug capture rotate error: {_rot_ex!r}")
        # Always wipe per-car DB on session reset.
        # The conditional tag-check was removed: if the overlay restarts mid-session the
        # tag matches and the DB would NOT be wiped, leaving stale LPIT/PIT/INC visible.
        try:
            _db = db_get()
            _db["_session_tag"] = "|".join(str(x) for x in sig)
            _db["cars"] = {}            # wipe inc, pen, pit, lpit, pittime, etc.
            db_flush(force=True)
        except Exception:
            pass

    # ---- EVENT-LEVEL tracking: qualify positions persist across sessions of the same event ----
    # Only clear _qualify_class_pos when the event itself changes (new track/session ID),
    # NOT when going from Qualify → Race (same event, different SessionNum).
    # sig tuple layout: (sid, sub, uid, sn, st, tid)
    _evt_sig = (sig[0], sig[5])   # (SessionID, TrackName)
    if _evt_sig != _EVENT_SIG[0]:
        if DEBUG:
            _log(f"Event reset: {_EVENT_SIG[0]} → {_evt_sig}  (qualify positions cleared)")
        _EVENT_SIG[0] = _evt_sig
        _qualify_class_pos.clear()

    # Populate qualify class positions (run every frame when empty; once filled it stays until event change).
    if not _qualify_class_pos:
        try:
            _si_q = sg("SessionInfo", None)
            if isinstance(_si_q, dict):
                _sessions_q = _si_q.get("Sessions") or []
                _best_q_idx = -1
                for _sq_i, _sq in enumerate(_sessions_q):
                    if not isinstance(_sq, dict):
                        continue
                    if "qualify" in str(_sq.get("SessionType", "")).lower():
                        _rp_q = _sq.get("ResultsPositions") or []
                        if _rp_q:    # only use if results are available
                            _best_q_idx = _sq_i
                if _best_q_idx >= 0:
                    for _rq in (_sessions_q[_best_q_idx].get("ResultsPositions") or []):
                        try:
                            _cidx_q = int(_rq.get("CarIdx", -1))
                            # ResultsPositions.ClassPosition is 0-indexed (P1=0),
                            # but CarIdxClassPosition is 1-indexed (P1=1). Normalise here.
                            _cpos_q = int(_rq.get("ClassPosition", -1)) + 1
                            if _cidx_q >= 0 and _cpos_q > 0:
                                _qualify_class_pos[_cidx_q] = _cpos_q
                        except Exception:
                            pass
        except Exception:
            pass

    try:
        onpit = sg("CarIdxOnPitRoad", [])
        lapc = sg("CarIdxLapCompleted", [])
        lastlt = sg("CarIdxLastLapTime", [])
        t = session_time()
        _finished_sector_laps = []
        _init_sectors()

        # ---- Reference-lap recorder: collect for every driver ----
        # Mirrors irdashies' useReferenceLapStoreUpdater — every paint tick
        # we feed each driver's (track_pct, session_time, on_pit_road) into
        # _collect_lap_data, which builds per-car best laps and per-class
        # persisted laps. The relative widget queries get_reference_lap()
        # using the BEHIND car's index/class to get the ruler for INT.
        # try:
        #     _dist_rec = sg("CarIdxLapDistPct", [])
        #     _dm_rec = driver_map() or {}
        #     _est_rec = sg("CarIdxEstTime", [])
        #     _update_est_time_profiles(_dm_rec, _dist_rec, _est_rec)
        #     _is_yellow = False
        #     try:
        #         _sf_now = int(sg("SessionFlags", 0) or 0)
        #         _is_yellow = bool(_sf_now & 0x4000) or bool(_sf_now & 0x8000)
        #     except Exception:
        #         _is_yellow = False
        #
        #     if isinstance(_dist_rec, (list, tuple)) and _dm_rec:
        #         for _ci_rec, _drv_rec in _dm_rec.items():
        #             try:
        #                 if _ci_rec >= len(_dist_rec):
        #                     continue
        #                 _tp = float(_dist_rec[_ci_rec])
        #                 if _tp <= -1:
        #                     continue
        #                 _cls = int(_drv_rec.get("CarClassID", 0) or 0)
        #                 _opit = bool(onpit[_ci_rec]) if isinstance(onpit, (list, tuple)) and _ci_rec < len(onpit) else False
        #                 _collect_lap_data(_ci_rec, _cls, _tp, t, 3, _opit, is_yellow=_is_yellow)
        #             except Exception:
        #                 continue
        # except Exception:
        #     pass
        pass  # 261001_CURSOR

        n = min(len(onpit), len(lapc), len(lastlt))
        for i in range(n):
            op = bool(onpit[i])

            # PIT ENTRY
            if op and not prev_on_pit[i]:
                pit_entry_time[i] = t
                last_pit_lap_completed[i] = _safe_int(lapc[i], 0)
                _plc = last_pit_lap_completed[i]
                _pit_laps[i].add(_plc + 1)  # in-lap (completes after pit exit)
                _pit_laps[i].add(_plc + 2)  # out-lap (first lap from cold tyres)

                drv = driver_map().get(i, {})
                if drv:
                    db_set_car_field(drv, i, "onpit", 1)
                    db_set_car_field(drv, i, "pit_entry_t", pit_entry_time.get(i, t))
                    db_set_car_field(drv, i, "lastpit_lap", last_pit_lap_completed.get(i, 0))

            # LATE-JOIN PIT DETECTION
            # If we observe a car ALREADY on pit road but have no record of
            # their entry (e.g., the user joined the race after this car
            # pitted, or the widget was hidden during the entry), best-guess
            # the entry as "happening now". The recorded lap is the car's
            # CURRENT lap completion, so when they leave pit and finish a
            # lap, LPIT will tick from 1 instead of staying empty.
            #
            # Without this, cars that were pitting at the moment we joined
            # the race had LPIT = "" forever — a real-world bug user hit at
            # Spa multi-class. Verified against data_20260506_174854.json.
            elif op and i not in pit_entry_time:
                pit_entry_time[i] = t
                last_pit_lap_completed[i] = _safe_int(lapc[i], 0)
                drv = driver_map().get(i, {})
                if drv:
                    db_set_car_field(drv, i, "onpit", 1)
                    db_set_car_field(drv, i, "pit_entry_t", pit_entry_time.get(i, t))
                    db_set_car_field(drv, i, "lastpit_lap", last_pit_lap_completed.get(i, 0))

            # PIT EXIT (store last pit duration forever)
            if (not op) and prev_on_pit[i]:
                t0 = pit_entry_time.get(i, None)
                if t0 is not None:
                    dur = session_time() - float(t0)
                    # Reject flicker noise: CarIdxOnPitRoad can briefly toggle
                    # True at pit lane boundary crossings (entry-line, exit-line,
                    # tow recovery, etc.) without an actual pit stop. A real pit
                    # stop — even a drive-through — is at least 5-10 seconds of
                    # pit-lane traversal. Using 5s as a safe lower bound to
                    # avoid persisting unrealistic values like 0.1-0.9s.
                    PIT_MIN_DURATION = 5.0
                    if dur >= PIT_MIN_DURATION:
                        drv = driver_map().get(i, {})
                        if drv:
                            db_set_car_field(drv, i, "lastpit_dur", float(dur))
                            db_set_car_field(drv, i, "lastpit_lap", last_pit_lap_completed.get(i, 0))
                            db_set_car_field(drv, i, "onpit", 0)
                    else:
                        # Flicker — also undo the in-lap/out-lap markers we set
                        # speculatively at PIT ENTRY, since no actual pit happened.
                        try:
                            _plc_flicker = last_pit_lap_completed.get(i, 0)
                            _pit_laps[i].discard(_plc_flicker + 1)
                            _pit_laps[i].discard(_plc_flicker + 2)
                        except Exception:
                            pass

            prev_on_pit[i] = op

            try:
                lc = int(lapc[i])
            except Exception:
                lc = 0

            if lc > last_lap_completed[i]:
                had_prev_lap = last_lap_completed[i] > 0
                _finished_sector_laps.append((
                    i, lc, last_lap_completed[i], _sf_cross_time.get(i),
                    dict(_sector_cross_time.get(i, {})), _sector_inc_at_sf.get(i),
                ))
                # Only record S/F crossing time on a REAL new lap, not the first observation.
                # On first observation last_lap_completed[i]==0 and lc may be 5+, which would
                # set a fake crossing time (current time ≠ actual S/F time).
                if had_prev_lap:
                    _sf_cross_time[i] = t
                    _sector_cross_time[i] = {}
                last_lap_completed[i] = lc
                try:
                    lt = float(lastlt[i])
                except Exception:
                    lt = -1
                if lt and lt > 0 and lc > 0:
                    # BEST follows our overlay rule, not iRacing validity:
                    # every sane completed lap observed for each car can win.
                    session_best_lap_update(i, lt)

        # ---- INCIDENTS: delta-accumulation, tow-proof ----
        # iRacing resets CarIdxIncidentCount[car_idx] when a car is towed.
        # We track raw deltas so the displayed count NEVER decreases within a session.
        # Incident points: 1x = track limit, 2x = contact, 4x = major crash
        ci_arr = sg("CarIdxIncidentCount", [])
        if isinstance(ci_arr, (list, tuple)):
            for _ci, _raw_v in enumerate(ci_arr):
                try:
                    _raw = int(float(_raw_v))
                except Exception:
                    continue
                _prev = _inc_prev_raw.get(_ci, -1)
                _acc  = _inc_cache.get(_ci, 0)
                if _prev < 0:
                    # First observation: start from 0, not from iRacing's current value.
                    # Seeding from _raw would carry over the previous session's incident
                    # count because iRacing may not reset CarIdxIncidentCount instantly.
                    _inc_cache[_ci] = 0
                elif _raw > _prev:
                    # Normal increase — add the delta (handles mid-race incidents)
                    _inc_cache[_ci] = _acc + (_raw - _prev)
                # If raw went down (tow/reset) we keep _acc unchanged (do nothing)
                _inc_prev_raw[_ci] = _raw

        # Cross-reference SessionInfo.Sessions[csn].ResultsPositions.Incidents
        # This is the authoritative per-car incident source — it includes ALL cars,
        # unlike DriverInfo.CurDriverIncidentCount which is -1 for most non-player cars.
        try:
            _si = sg("SessionInfo", None)
            if isinstance(_si, dict):
                _csn = int(sg("SessionNum", 0) or 0)
                _sessions = _si.get("Sessions") or []
                if isinstance(_sessions, list) and 0 <= _csn < len(_sessions):
                    for _res in (_sessions[_csn].get("ResultsPositions") or []):
                        try:
                            _cidx = int(_res.get("CarIdx", -1))
                            _inc_yaml = int(float(_res.get("Incidents", 0) or 0))
                            if _cidx >= 0 and _inc_yaml > _inc_cache.get(_cidx, 0):
                                _inc_cache[_cidx] = _inc_yaml
                        except Exception:
                            pass
        except Exception:
            pass

        # DriverInfo per-driver fields: mostly -1 for other cars, but use if positive
        _dm_inc = driver_map()
        for _ci, _drv in _dm_inc.items():
            for _field in ("CurDriverIncidentCount", "TeamIncidentCount"):
                try:
                    _yaml_v = int(float(_drv.get(_field, 0) or 0))
                    if _yaml_v > 0 and _yaml_v > _inc_cache.get(_ci, 0):
                        _inc_cache[_ci] = _yaml_v
                except Exception:
                    pass

        # ---- Heuristic incident detection for non-player cars ----
        # iRacing doesn't broadcast CarIdxIncidentCount per-car during race
        # (verified across many capture files: always 0 or absent), and YAML
        # ResultsPositions.Incidents is also unavailable mid-race. So for
        # non-player cars we infer incidents from observable behaviour:
        #
        #   +1x  off-track: CarIdxTrackSurface transitions from OnTrack(3)
        #        to OffTrack(0) AND stays off for >=0.5s. Filters momentary
        #        wheel-off-curb noise. Cooldown 5s so a single long off
        #        only counts once.
        #
        #   +2x  spin / stopped on track: CarIdxLapDistPct stalls (delta
        #        below 0.0001 over 3 seconds, ~ <0.5 m of motion) while
        #        the car is OnTrack and the race is GREEN (not under
        #        caution — yellow-flag stops are routine). Cooldown 15s.
        #
        # Crash (+4x) detection requires reliable speed/contact telemetry
        # for other cars which iRacing doesn't expose; intentionally
        # omitted. The user can flag specific incidents through the RPT
        # column if a specific case needs to be reviewed offline.
        #
        # Player keeps the real CarIdxIncidentCount from layers above
        # (which IS broadcast for the player and used by INFO/INC).
        try:
            _surf_arr = sg("CarIdxTrackSurface", []) or []
            _dp_arr   = sg("CarIdxLapDistPct", []) or []
            _op_arr   = sg("CarIdxOnPitRoad", []) or []
            _lapc_arr = sg("CarIdxLapCompleted", []) or []
            # Yellow flag detection — skip stalled-on-track scoring under caution
            _sf_raw = int(sg("SessionFlags", 0) or 0)
            _is_yellow = bool(_sf_raw & 0x4000) or bool(_sf_raw & 0x8000)
            try:
                _sess_state = int(sg("SessionState", 0) or 0)
            except Exception:
                _sess_state = 0
            _is_racing_state = (_sess_state == 4)
            _t_now = t   # session_time from earlier in this function

            _player_idx = player_idx()
            try:
                _player_lc = int(_lapc_arr[_player_idx]) if _player_idx < len(_lapc_arr) else -1
            except Exception:
                _player_lc = -1
            _player_ready = (_player_lc >= 0)

            # Do not infer incidents while the new session is still bootstrapping
            # (grid/loading/lap=-1). Otherwise stopped-grid cars get false +2/+4.
            if (not _is_racing_state) or (not _player_ready):
                _inc_surf_prev.clear()
                _inc_offtrack_t.clear()
                _inc_offtrack_until.clear()
                _inc_dp_hist.clear()
                _inc_stopped_until.clear()
                _inc_stopped_at.clear()
                _inc_crash_until.clear()
                _inc_stop_score.clear()
                n_inc = 0
            else:
                n_inc = min(len(_surf_arr), len(_dp_arr))
            for _ci in range(n_inc):
                # Skip player — real iRacing count is authoritative
                if _ci == _player_idx:
                    continue
                # Skip cars on pit road / not in world / safety car
                try:
                    _surf = int(_surf_arr[_ci])
                    _dp = float(_dp_arr[_ci])
                except Exception:
                    continue
                if _surf < 0 or _dp < 0:
                    continue
                _drv_ci = _dm_inc.get(_ci, {})
                if _is_safety_car(_drv_ci):
                    continue
                _on_pit = bool(_op_arr[_ci]) if _ci < len(_op_arr) else False
                if _on_pit:
                    continue

                # --- Off-track detection ---
                _prev_surf = _inc_surf_prev.get(_ci)
                if _prev_surf is not None:
                    # Transition into OffTrack (surface=0)
                    if _surf == 0 and _prev_surf != 0:
                        _inc_offtrack_t[_ci] = _t_now
                    # Came back on track (surface=3) after being off for >=0.5s
                    elif _surf == 3 and _prev_surf == 0:
                        _off_start = _inc_offtrack_t.get(_ci, _t_now)
                        _off_dur = _t_now - _off_start
                        _cooldown_until = _inc_offtrack_until.get(_ci, 0)
                        if _off_dur >= 0.5 and _t_now >= _cooldown_until:
                            _inc_cache[_ci] = _inc_cache.get(_ci, 0) + 1
                            _inc_offtrack_until[_ci] = _t_now + 5.0
                _inc_surf_prev[_ci] = _surf

                # --- Stopped-on-track detection (spin / crash) ---
                # Only under green flag, on track surface
                if _surf == 3 and not _is_yellow:
                    _hist = _inc_dp_hist.setdefault(_ci, [])
                    _hist.append((_t_now, _dp))
                    # Keep ~3-second window
                    while _hist and (_t_now - _hist[0][0]) > 3.0:
                        _hist.pop(0)
                    if len(_hist) >= 6:
                        _t_old, _dp_old = _hist[0]
                        _dt = _t_now - _t_old
                        if _dt >= 2.5:
                            # Compute MOVED distance, accounting for wrap
                            _dp_diff = _dp - _dp_old
                            if _dp_diff < -0.5:
                                _dp_diff += 1.0
                            elif _dp_diff > 0.5:
                                _dp_diff -= 1.0
                            # Stopped = barely moved in 2.5+ seconds
                            if abs(_dp_diff) < 0.0001:
                                # Check crash vs spin: is there ANOTHER car
                                # also stopped within ±0.005 dp (~ a few
                                # meters) of THIS car? Same time window
                                # ("stopped" recently) means they likely
                                # made contact rather than independently
                                # spinning. Score +4x for BOTH cars and
                                # SKIP the +2 spin (would double-count).
                                _prior_score = _inc_stop_score.get(_ci, 0)
                                _crash_cooldown = _inc_crash_until.get(_ci, 0)
                                _is_crash = False
                                if _prior_score < 4 and _t_now >= _crash_cooldown:
                                    for _other_ci, (_other_t, _other_dp) in list(_inc_stopped_at.items()):
                                        if _other_ci == _ci:
                                            continue
                                        # Must have stopped within the last
                                        # 5 seconds AND still be there
                                        if (_t_now - _other_t) > 5.0:
                                            continue
                                        # Proximity: within 0.005 of track
                                        # (= a few meters on most tracks)
                                        _gap = _dp - _other_dp
                                        if _gap < -0.5: _gap += 1.0
                                        elif _gap > 0.5: _gap -= 1.0
                                        if abs(_gap) <= 0.005:
                                            # Other car must not be in crash cooldown either
                                            if _t_now >= _inc_crash_until.get(_other_ci, 0):
                                                _is_crash = True
                                                _other_prior = _inc_stop_score.get(_other_ci, 0)
                                                _inc_cache[_ci] = (
                                                    _inc_cache.get(_ci, 0)
                                                    + max(0, 4 - _prior_score)
                                                )
                                                _inc_cache[_other_ci] = (
                                                    _inc_cache.get(_other_ci, 0)
                                                    + max(0, 4 - _other_prior)
                                                )
                                                _inc_stop_score[_ci] = 4
                                                _inc_stop_score[_other_ci] = 4
                                                _inc_crash_until[_ci]       = _t_now + 30.0
                                                _inc_crash_until[_other_ci] = _t_now + 30.0
                                                # Both cars also get the spin
                                                # cooldown so the SOLO spin
                                                # path doesn't fire next tick
                                                _inc_stopped_until[_ci]       = _t_now + 15.0
                                                _inc_stopped_until[_other_ci] = _t_now + 15.0
                                                if DEBUG:
                                                    _log(f"Heuristic CRASH: car {_ci} + car {_other_ci} "
                                                         f"both stopped at dp~{_dp:.4f}  → +4 each")
                                                break
                                # If no crash pair detected, fall back to
                                # solo-spin scoring (+2). Note this still
                                # respects the SPIN cooldown so we don't
                                # double-count an ongoing stop.
                                if not _is_crash and _prior_score == 0:
                                    _cooldown_until = _inc_stopped_until.get(_ci, 0)
                                    if _t_now >= _cooldown_until:
                                        _inc_cache[_ci] = _inc_cache.get(_ci, 0) + 2
                                        _inc_stopped_until[_ci] = _t_now + 15.0
                                        _inc_stop_score[_ci] = 2
                                # Record this car as "stopped at this dp/time"
                                # so OTHER cars stopping nearby in the next
                                # few seconds can pair with it as a crash.
                                _inc_stopped_at[_ci] = (_t_now, _dp)
                            else:
                                # The car moved again: a future stop is a new
                                # episode and may be scored once.
                                _inc_stop_score.pop(_ci, None)
                                _inc_stopped_at.pop(_ci, None)
                else:
                    # Not eligible for spin detection — clear history so the
                    # window doesn't carry stale yellow/pit-road samples.
                    _inc_dp_hist.pop(_ci, None)
                    # Clear stopped-at record too — only keep cars currently
                    # stopped under green so the crash-pair lookup stays clean.
                    _inc_stopped_at.pop(_ci, None)
                    _inc_stop_score.pop(_ci, None)

            # Garbage-collect stopped_at entries older than 5s — these can't
            # pair with any new stop and just take up space.
            try:
                _stale_cutoff = _t_now - 5.0
                for _stale_ci in [k for k, (st, _) in _inc_stopped_at.items() if st < _stale_cutoff]:
                    _inc_stopped_at.pop(_stale_ci, None)
            except Exception:
                pass
        except Exception as _e:
            if DEBUG:
                _log(f"heuristic inc detection error: {_e!r}")

        # --- Sector crossing detection ---
        # Must run after the S/F crossing detection above so _sf_cross_time is already updated.
        # Incidents for this frame have now been accumulated. Validate the
        # whole completed lap before adding any sector to the session means.
        for _i, _lc, _previous_lc, _start, _crossings, _previous_inc in _finished_sector_laps:
            _inc = _inc_cache.get(_i, 0)
            # AVG uses the rolling clean-lap history, LAST reads SDK's latest
            # completed lap. Accumulate this frame's incidents before deciding
            # whether the just-finished lap is clean (including finish-line 1x).
            _previous_lap_inc = _inc_at_sf.get(_i)
            _lap_time = _normalize_lap_time_sec(lastlt[_i] if _i < len(lastlt) else None)
            if (_lap_time is not None and _lc == _previous_lc + 1 and _previous_lc > 0
                    and _previous_lap_inc is not None and _inc == _previous_lap_inc
                    and _lc not in _pit_laps[_i] and not onpit[_i]):
                lap_hist[_i].append(_lap_time)
            _inc_at_sf[_i] = _inc
            # Sectors include incident/pit laps; only telemetry completeness
            # matters here. The separate clean AVG history above is unchanged.
            _sector_complete = (_lc == _previous_lc + 1
                                and 0 <= t - _sector_prev_sample_t.get(_i, t - 3) <= 2)
            _final_sector_start = _crossings.get(len(_sector_pcts) - 1) if _sector_pcts else _start
            if (_lc == _previous_lc + 1 and _final_sector_start is not None
                    and 0 <= t - _sector_prev_sample_t.get(_i, t - 3) <= 2):
                sector_history.record_sector(_i, len(_sector_pcts), t - _final_sector_start)
            sector_history.record_lap(
                _i, _start, _crossings, t,
                lastlt[_i] if _i < len(lastlt) else None,
                len(_sector_pcts) + 1, complete=_sector_complete,
            )
            _sector_inc_at_sf[_i] = _inc
        _dp_arr = sg("CarIdxLapDistPct", [])
        if isinstance(_dp_arr, (list, tuple)):
            for _i in range(min(n, len(_dp_arr))):
                try:
                    _dp_new = float(_dp_arr[_i])
                    _sample_t = _sector_prev_sample_t.get(_i, t)
                    _sector_prev_sample_t[_i] = t
                    if not math.isfinite(_dp_new) or not 0 <= _dp_new <= 1 or not 0 <= t - _sample_t <= 2:
                        _sf_cross_time.pop(_i, None)
                        _sector_cross_time.pop(_i, None)
                        _prev_dp.pop(_i, None)
                        continue
                    _dp_old = _prev_dp.get(_i, _dp_new)
                    if _dp_new < _dp_old - 0.002 and not (_dp_old > 0.9 and _dp_new < 0.1):
                        _sf_cross_time.pop(_i, None)
                        _sector_cross_time.pop(_i, None)
                    # Only track sector crossings once we have a S/F anchor for this car
                    if _i in _sf_cross_time and _sector_pcts:
                        for _s_idx, _s_pct in enumerate(_sector_pcts):
                            if _dp_old < _s_pct <= _dp_new:
                                _crossings = _sector_cross_time.setdefault(_i, {})
                                _sector_start = _sf_cross_time[_i] if _s_idx == 0 else _crossings.get(_s_idx - 1)
                                if _sector_start is not None:
                                    sector_history.record_sector(_i, _s_idx, t - _sector_start)
                                _sector_cross_time.setdefault(_i, {})[_s_idx] = t
                    _prev_dp[_i] = _dp_new
                except Exception:
                    pass

        # Compact continuous capture: 2 Hz, flushed in 15-second blocks.
        # This retains all fields needed by the offline audit while avoiding
        # the multi-gigabyte files produced by repeating every SDK variable
        # and full YAML tree ten times per second.
        if DEBUG:
            now = time.time()
            if now - _FULL_CAPTURE["last_sample_t"] >= _CAPTURE_SAMPLE_SECONDS:
                snap = _collect_full_snapshot_raw(return_snap=True)
                if snap:
                    _CAPTURE_BUFFER.append(snap)
                _FULL_CAPTURE["last_sample_t"] = now

            if now - _FULL_CAPTURE["block_start_t"] >= _CAPTURE_BLOCK_SECONDS:
                if _CAPTURE_BUFFER:
                    _append_jsonl({
                        "tag": "block",
                        "schema": 2,
                        "start": _FULL_CAPTURE["block_start_t"],
                        "end": now,
                        "meta": _collect_capture_metadata(),
                        "samples": _CAPTURE_BUFFER,
                    })
                    _CAPTURE_BUFFER.clear()
                _FULL_CAPTURE["block_start_t"] = now

    except Exception as e:
        _log(f"update_state error: {e!r}")


def session_rubber_text():
    v = sg("SessionTrackRubberState", None)
    if v is None:
        v = sg("TrackRubber", None)
    if v is None:
        v = sg("TrackRubberState", None)
    if v is None:
        return ""
    try:
        if isinstance(v, str):
            return v
        i = int(v)
    except Exception:
        return str(v)
    return {
        0: "NONE",
        1: "LOW",
        2: "MED",
        3: "HIGH",
        4: "MAX",
    }.get(i, str(i))

def debug_dump_all_vars(tag="vars", limit=0):
    try:
        names = []
        try:
            names = list(getattr(ir, "var_headers_names", []) or [])
        except Exception:
            pass
        if not names:
            try:
                names = sorted(list(getattr(ir, "vars", {}).keys()))
            except Exception:
                names = []

        out = {"tag": tag, "count": len(names)}
        n = 0
        for k in names:
            if limit and n >= limit:
                break
            try:
                v = sg(k, None)
            except Exception:
                continue
            try:
                if isinstance(v, (list, tuple)):
                    out[k] = list(v[:20])
                else:
                    out[k] = v
            except Exception:
                out[k] = str(v)
            n += 1

        _append_jsonl(out)
        _log(f"debug_dump_all_vars: wrote {n}/{len(names)} vars to data.json")
    except Exception as e:
        _log(f"debug_dump_all_vars error: {e!r}")


_CAPTURE_SCALARS = (
    "SessionTime", "SessionTick", "SessionNum", "SessionState",
    "SessionUniqueID", "SessionFlags", "SessionTimeRemain",
    "SessionLapsRemain", "SessionLapsRemainEx", "SessionLapsTotal",
    "PlayerCarIdx", "PlayerCarPosition", "PlayerCarClassPosition",
    "PlayerCarMyIncidentCount", "PlayerCarTeamIncidentCount",
    "PlayerCarDriverIncidentCount", "PlayerIncidents",
    "Lap", "LapCompleted", "LapDistPct", "LapCurrentLapTime",
    "LapLastLapTime", "LapBestLapTime", "FuelLevel", "FuelLevelPct",
    "FuelUsePerHour", "FuelPress", "Speed", "OnPitRoad", "IsOnTrack",
    "IsInGarage", "PlayerTrackSurface", "PlayerTrackSurfaceMaterial",
    "PitstopActive", "PlayerCarInPitStall", "PitSvFlags", "PitSvFuel",
    "AirTemp", "TrackTemp", "TrackTempCrew", "TrackWetness",
)

_CAPTURE_ARRAYS = (
    "CarIdxBestLapTime", "CarIdxBestLapNum", "CarIdxClass",
    "CarIdxClassPosition", "CarIdxEstTime", "CarIdxF2Time",
    "CarIdxLap", "CarIdxLapCompleted", "CarIdxLapDistPct",
    "CarIdxLastLapTime", "CarIdxOnPitRoad", "CarIdxPosition",
    "CarIdxSessionFlags", "CarIdxTrackSurface",
    "CarIdxTrackSurfaceMaterial", "CarIdxTireCompound",
    "CarIdxGear", "CarIdxRPM",
)

_CAPTURE_TYRE_FIELDS = tuple(
    f"{corner}{suffix}"
    for corner in ("LF", "RF", "LR", "RR")
    for suffix in (
        "tempCL", "tempCM", "tempCR",
        "wearL", "wearM", "wearR", "coldPressure",
    )
)


def _compact_driver_info():
    info = sg("DriverInfo", None) or {}
    drivers = []
    keep = (
        "CarIdx", "CarID", "CarPath", "CarClassID", "CarClassEstLapTime",
        "CarNumber", "CarScreenNameShort", "CarIsPaceCar", "UserID",
        "UserName", "TeamID", "TeamName",
    )
    for driver in info.get("Drivers") or []:
        if isinstance(driver, dict):
            drivers.append({key: driver.get(key) for key in keep})
    return {"DriverCarIdx": info.get("DriverCarIdx"), "Drivers": drivers}


def _collect_capture_metadata():
    result = {"DriverInfo": _compact_driver_info()}
    try:
        result["TelemetryLayout"] = telemetry_layout_status(include_fields=True)
    except Exception:
        pass
    try:
        weekend = sg("WeekendInfo", None) or {}
        result["WeekendInfo"] = {
            key: weekend.get(key)
            for key in (
                "SessionID", "SubSessionID", "TrackName", "TrackID",
                "TrackDisplayName", "TrackLength", "Category",
            )
        }
    except Exception:
        pass
    try:
        sessions = (sg("SessionInfo", None) or {}).get("Sessions") or []
        session_num = int(sg("SessionNum", 0) or 0)
        if 0 <= session_num < len(sessions):
            session = sessions[session_num] or {}
            result["Session"] = {
                "SessionNum": session.get("SessionNum"),
                "SessionType": session.get("SessionType"),
                "SessionName": session.get("SessionName"),
                "ResultsPositions": session.get("ResultsPositions") or [],
            }
    except Exception:
        pass
    return result


def _collect_full_snapshot_raw(return_snap=False):
    try:
        snap = {"tag": "compact", "schema": 2}
        snap["_telemetry"] = {
            "generation": int(_TELEMETRY_LAYOUT.get("generation", 0)),
            "root": list(_telemetry_root_signature() or ()),
        }

        for k in _CAPTURE_SCALARS + _CAPTURE_ARRAYS + _CAPTURE_TYRE_FIELDS:
            try:
                v = sg(k, None)
            except Exception:
                continue

            try:
                if isinstance(v, (list, tuple)):
                    snap[k] = list(v)
                else:
                    snap[k] = v
            except Exception:
                snap[k] = str(v)

        # YAML root subtrees — pyirsdk exposes these via `ir[key]` (bracket
        # access falls through to session_info parsing). The legacy approach
        # `getattr(ir, "session_info", None)` returned None in practice in
        # capture context (the property didn't always materialise mid-tick),
        # leaving 60k+ samples with no SessionInfo. Reading via ir[] mirrors
        # the live overlay paths (e.g. driver_map calls sg("DriverInfo")).
        snap["DriverInfo"] = _compact_driver_info()
        try:
            weekend = sg("WeekendInfo", None) or {}
            snap["WeekendInfo"] = {
                key: weekend.get(key)
                for key in ("SessionID", "SubSessionID", "TrackName", "TrackID")
            }
        except Exception:
            pass

        # What the overlay actually DISPLAYED at this tick — fuel numbers,
        # relative rows, standings rows, etc. Populated by each widget via
        # update_state_and_debug_dump(extra=...). This is the ground truth
        # for "did the overlay show the right thing?" debugging, and is
        # what capture_inspect.py reads under snap["_widgets"].
        try:
            if _LAST_WIDGET_EXTRAS:
                # deep-ish copy: top-level dict, shallow-copy any inner dict/list
                # so later mutations by widgets don't alias into past samples.
                _w = {}
                for _k, _v in _LAST_WIDGET_EXTRAS.items():
                    if isinstance(_v, dict):
                        _w[_k] = dict(_v)
                    elif isinstance(_v, list):
                        _w[_k] = list(_v)
                    else:
                        _w[_k] = _v
                snap["_widgets"] = _w
        except Exception:
            pass

        if return_snap:
            return snap
        else:
            _append_jsonl(snap)

    except Exception as e:
        _log(f"_collect_full_snapshot_raw error: {e!r}")


# if correct reply yes, else return solutions that are mandatory to work
