# weather
#
# Used to be called "info" before this rename. The original cell layout was
# Rubber / Temp(=TrackTemp) / Track(=DRY/M-DRY state) / Wet / Prec. New layout
# (per user spec):
#   Rubber → Temp(AirTemp) → Track(TrackTemp) → Wet → Condition → Prec
# i.e. the old "Temp" column moves under the label "Track" and a new "Temp"
# column is inserted right after Rubber to show the AIR temperature.

from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QRect
from base import RowBar
from weather_columns import WEATHER_COLUMNS, weather_columns
import traceback
import core


_RUBBER_MAP = {
    "simulated green":            "NONE",
    "carry over":                 "CARRY",
    "slight carry over":          "SLIGHT",
    "low carry over":             "LOW",
    "moderately low carry over":  "LO-MED",
    "moderate carry over":        "MED",
    "moderately high carry over": "MED-HI",
    "high carry over":            "HIGH",
    "heavily rutted carry over":  "HIGH",
    "green":                      "NONE",
    "slight usage":               "SLIGHT",
    "low usage":                  "LOW",
    "moderately low usage":       "LO-MED",
    "moderate usage":             "MED",
    "moderately high usage":      "MED-HI",
    "high usage":                 "HIGH",
    "heavily rutted usage":       "HIGH",
}

_TRACK_WETNESS = {
    1: "dry",
    2: "mostly dry",
    3: "very lightly wet",
    4: "lightly wet",
    5: "moderately wet",
    6: "very wet",
    7: "extremely wet",
}


def _track_wetness_label(raw) -> str:
    """Describe the SDK TrackWetness enum; unknown values add no detail."""
    if raw is None or isinstance(raw, bool):
        return ""
    if isinstance(raw, str):
        value = raw.strip()
        if not value or value.lower() == "unknown":
            return ""
        if not value.isdecimal():
            return value
        raw = int(value)
    return _TRACK_WETNESS.get(raw, "")


def _rubber_label(raw: str) -> str:
    if not raw:
        return ""
    key = raw.strip().lower()
    if key in _RUBBER_MAP:
        return _RUBBER_MAP[key]
    for suffix in (" usage", " carry over"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
            break
    return (key.upper() if key else raw.strip())[:7].rstrip()


class Weather(RowBar):
    def __init__(self):
        settings = core.cfg.setdefault("weather_settings", {})
        settings["columns"] = weather_columns(settings.get("columns"))
        super().__init__("weather", "weather_settings", WEATHER_COLUMNS)
        self._last_payload = {}

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    def paintEvent(self, e):
        try:
            p = QPainter(self)

            if not core.ir.is_connected:
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_normal)
                p.setPen(core.CLR_WHITE)
                p.drawText(QRect(core.PAD_X, core.PAD_Y,
                                 self.width() - 2 * core.PAD_X,
                                 self.height() - 2 * core.PAD_Y),
                           Qt.AlignmentFlag.AlignCenter,
                           "WEATHER: DISCONNECTED")
                return

            # ---- gather values ----
            rubber = ""
            try:
                _rub_candidates = []
                si = core.sg("SessionInfo", None)
                if si and isinstance(si, dict):
                    csn = int(core.sg("SessionNum", 0) or 0)
                    sessions = si.get("Sessions") or []
                    if isinstance(sessions, list):
                        for _si_idx in range(min(csn, len(sessions) - 1), -1, -1):
                            _sess = sessions[_si_idx]
                            if not isinstance(_sess, dict):
                                continue
                            _raw = str(_sess.get("SessionTrackRubberState", "") or "").strip()
                            if _raw:
                                _rub_candidates.append(_raw)
                wi = core.sg("WeekendInfo", None)
                if wi and isinstance(wi, dict):
                    _wr = str(wi.get("TrackRubberState", "") or "").strip()
                    if _wr:
                        _rub_candidates.append(_wr)
                for _c in _rub_candidates:
                    if "carry over" not in _c.lower():
                        rubber = _c
                        break
                if not rubber and _rub_candidates:
                    rubber = _rub_candidates[0]
            except Exception as _e:
                core._log(f"Weather rubber error: {_e!r}")
                rubber = ""

            # AIR temperature (new "Temp" cell)
            air_temp = core.sg("AirTemp", None)
            air_s = ""
            if air_temp is not None:
                try:
                    air_s = str(int(round(float(air_temp))))
                except Exception:
                    air_s = ""

            # TRACK temperature (renamed "Track" cell — was previously "Temp")
            track_temp = core.sg("TrackTemp", None)
            if track_temp is None:
                track_temp = core.sg("TrackTempCrew", None)
            track_s = ""
            if track_temp is not None:
                try:
                    track_s = str(int(round(float(track_temp))))
                except Exception:
                    track_s = ""

            declared_wet = core.sg("WeatherDeclaredWet", None)
            declared_wet_txt = ""
            try:
                if declared_wet is not None:
                    declared_wet_txt = "YES" if bool(declared_wet) else "NO"
            except Exception:
                declared_wet_txt = ""
            track_wetness = _track_wetness_label(core.sg("TrackWetness", None))
            wet_display = declared_wet_txt or "—"

            precip = core.sg("Precipitation", None)
            rubber = _rubber_label(rubber)

            self._last_payload = {
                "Rubber": rubber or "",
                "AirTemp": air_s,
                "TrackTemp": track_s,
                "Wet": wet_display,
                "TrackWetness": track_wetness,
                "Prec": ("" if precip is None else f"{float(precip):.2f}"),
            }
            core.update_state_and_debug_dump(extra={"weather": self._last_payload})

            col_lookup = self._column_lookup()
            def _t(cid, value, color=core.CLR_WHITE):
                cfg = col_lookup.get(cid) or {}
                lbl = cfg.get("label", cid.upper())
                if cid == "wet":
                    lbl = str(lbl).upper().rstrip(":")
                sep = ": " if cid == "wet" else " "
                return (cid, f"{lbl}{sep}{value}" if lbl else str(value), color)

            cells = [
                _t("rubber", rubber or "—"),
                _t("temp",   air_s or "—"),
                _t("track",  track_s or "—"),
                _t("wet",    wet_display),
                _t("condition", track_wetness.title() or "—"),
                _t("prec",   ("—" if precip is None else f"{float(precip):.2f}")),
            ]
            self._draw_row(p, cells)

        except Exception as ex:
            core._log(f"Weather paint error: {ex!r}")
            core._log(traceback.format_exc())
