"""Exercise the real widgets offscreen, without importing side-effectful core."""
import json
import os
from pathlib import Path
import sys
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "main"))
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor, QFont, QImage

APP = QApplication.instance() or QApplication([])
core = types.ModuleType("core")
sys.modules["core"] = core
core.cfg = json.loads((ROOT / "main/factory-overlay.json").read_text(encoding="utf-8"))
for name, rgb in {
    "WHITE": (255,255,255), "BLACK": (0,0,0), "GREEN": (0,255,0),
    "RED": (255,0,0), "GRID": (70,70,70), "ROW_A": (0,0,0),
    "ROW_B": (25,25,25), "PLAYER_BG": (255,255,255),
}.items():
    setattr(core, "CLR_" + name, QColor(*rgb))
core.FONT_NORMAL = QFont("Consolas", 10)
core.FONT_BOLD = QFont("Consolas", 10)
core.ROW_H, core.PAD_X, core.PAD_Y = 18, 3, 3
core._SESSION_SIG, core._RESET_EPOCH = ["test"], [0]
core.start_class_pos, core._inc_cache = {}, {}
core.pit_entry_time, core.last_pit_lap_completed = {}, {}
core.ir = types.SimpleNamespace(is_connected=True)
core.is_in_reset_grace = lambda: False
core.init_start_positions = lambda: None
core.save_cfg = lambda: None
core.connect = lambda: True
core.begin_frame = lambda: True
core.errors = []
core._log = core.errors.append
core.telemetry = {}
core.session = {}
core.sg = lambda key, default=None: core.telemetry.get(key, core.session.get(key, default))
core.player_idx = lambda: core.telemetry.get("PlayerCarIdx", 0)
core.session_time = lambda: core.sg("SessionTime", 0)
core.driver_map = lambda: {d["CarIdx"]: d for d in core.session.get("DriverInfo", {}).get("Drivers", [])}
core._is_safety_car = lambda d: bool(d.get("CarIsPaceCar"))
core.avg_sec_filtered = lambda *args: None
core.best_last = lambda idx: ("", "")
core.brand3 = lambda name: name[:3].upper()
core.class_color = lambda cid: core.CLR_WHITE
core.pos_gain = lambda *args: ("", core.CLR_WHITE)
core.pit_last_lap = lambda *args: None
core.pit_time = lambda *args: ""
core.ir_short = lambda *args: ""
core.sr_color_from_lic = lambda *args: core.CLR_WHITE
core.tire_letter = lambda *args: ""
core.blacklist_ids = lambda: set()
core.fmt_time_1 = lambda sec: f"{int(sec // 60)}:{sec % 60:04.1f}"
core.update_state_and_debug_dump = lambda **kwargs: None
core.telemetry_layout_status = lambda: {"generation": 0}

from relative import Relative
from fuel import Fuel
from standings import Standings
from weather import Weather


def render(widget):
    widget._vis_timer.stop()
    image = QImage(widget.size(), QImage.Format.Format_ARGB32)
    image.fill(0)
    widget.render(image)
    if image.size() != widget.size():
        image = QImage(widget.size(), QImage.Format.Format_ARGB32)
        image.fill(0)
        widget.render(image)
    if core.errors:
        raise AssertionError("\n".join(core.errors))
    return image


def set_data(telemetry, session):
    core.telemetry = telemetry
    core.session = session
    core.errors.clear()


def basic_data():
    session = {
        "DriverInfo": {"Drivers": [
            {"CarIdx": 0, "CarPath": "a", "CarClassID": 1, "CarClassEstLapTime": 100,
             "CarNumber": "1", "FlairName": "Germany"},
            {"CarIdx": 1, "CarPath": "b", "CarClassID": 1, "CarClassEstLapTime": 120,
             "CarNumber": "2", "FlairName": "United Kingdom"},
            {"CarIdx": 2, "CarPath": "a", "CarClassID": 1, "CarClassEstLapTime": 100,
             "CarNumber": "3", "FlairName": "Nigeria"}]},
        "WeekendInfo": {"TrackLength": "4 km", "TrackID": 1},
        "SessionInfo": {"Sessions": [{"SessionType": "Race"}]},
    }
    telemetry = dict(PlayerCarIdx=0, SessionTime=1000, SessionNum=0, SessionState=4,
                     SessionFlags=0, SessionLapsTotal=32767, SessionLapsRemainEx=32767,
                     SessionTimeRemain=100, FuelLevel=3.0,
                     CarIdxLapCompleted=[10, 10, 10], CarIdxLapDistPct=[.4, .41, .42],
                     CarIdxEstTime=[35, 50, 41], CarIdxTrackSurface=[3, 3, 3],
                     CarIdxOnPitRoad=[False]*3, CarIdxPosition=[2,3,1],
                     CarIdxClassPosition=[2,3,1], CarIdxSessionFlags=[0]*3,
                     CarIdxLastLapTime=[100,110,100], CarIdxBestLapTime=[100,110,100])
    return telemetry, session
