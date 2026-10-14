# info
#
# Race-progress widget. Shows two cells:
#   LAPS   xx/xx        — current/expected laps (no extra prefix/parens)
#   TIME   mm:ss        — countdown for time-based races (race ends when the
#                          clock runs out), count-up for lap-based races
#                          (oval / Porsche Cup style — race ends after a
#                          fixed number of laps so the elapsed time is the
#                          relevant figure).
#
# Same RowBar look-and-feel as FUEL / WEATHER (cells with vertical separator).

from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QRect
import math
import time as _wallclock
import traceback

import core
from base import RowBar
from fuel_projection import build_finish_projection  # 261001_CURSOR


_DEFAULT_COLUMNS = [
    {"id": "laps",     "label": "LAPS",    "width": 130, "enabled": True},
    {"id": "time",     "label": "TIME",    "width": 90,  "enabled": True},
    {"id": "simtime",  "label": "SimTime", "width": 80,  "enabled": True},
    {"id": "realtime", "label": "RealTime","width": 80,  "enabled": True},
    {"id": "inc",      "label": "INC",     "width": 80,  "enabled": True},
]


def _fmt_mmss(seconds):
    if seconds is None:
        return "—"
    try:
        s = float(seconds)
    except Exception:
        return "—"
    if s < 0:
        return "—"
    m = int(s // 60)
    sec = int(s - m * 60)
    if m >= 60:
        h = m // 60
        m = m - h * 60
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def _lt_for(ci, lastlt_arr, bestlt_arr):
    """Best-effort laptime for a car: last lap → best lap → None."""
    try:
        if lastlt_arr and len(lastlt_arr) > ci:
            v = float(lastlt_arr[ci])
            if v > 20:
                return v
    except Exception:
        pass
    try:
        if bestlt_arr and len(bestlt_arr) > ci:
            v = float(bestlt_arr[ci])
            if v > 20:
                return v
    except Exception:
        pass
    try:
        v = core.avg_sec(ci, 3)
        if v and v > 20:
            return v
    except Exception:
        pass
    return None


class Info(RowBar):
    """Compact race-progress strip — LAPS + TIME."""

    def __init__(self):
        super().__init__("info", "info_settings", _DEFAULT_COLUMNS)
        self._last_payload = {}
        self._checkered_finish_lap = None  # 261001_CURSOR

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
                           Qt.AlignmentFlag.AlignCenter, "INFO: DISCONNECTED")
                return

            # ---- Reset-grace placeholder ----
            # When the user transitions practice → qualify → race, the iRacing
            # YAML cache (driver list, WeekendOptions, etc.) and the live
            # PlayerCarTeamIncidentCount value can lag the actual session
            # transition by several seconds. Without this gate, INC would
            # briefly show the OLD session's incident count (e.g. 12 from
            # practice) before iRacing zeroes it for the new session, and the
            # user reported this stale-INC bleed-through across qualify. The
            # 6-second grace window matches the FUEL widget — long enough to
            # cover the YAML/telemetry refresh, short enough that a real
            # new-session render lands quickly.
            if core.is_in_reset_grace():
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_bold)
                p.setPen(QColor(255, 200, 0))
                p.drawText(QRect(core.PAD_X, core.PAD_Y,
                                 self.width() - 2 * core.PAD_X,
                                 self.height() - 2 * core.PAD_Y),
                           Qt.AlignmentFlag.AlignCenter,
                           "INFO: NEW SESSION…")
                return

            # ---- Detect race format (time vs lap cap) ----
            # 32767 (0x7FFF) is iRacing's "no lap cap" sentinel; anything
            # in (0, 32767) means it's a lap-capped race like an oval or
            # Porsche Cup short sprint.
            slt = core.sg("SessionLapsTotal", None)
            try:
                slt_i = int(slt) if slt is not None else None
            except Exception:
                slt_i = None
            is_lap_race = slt_i is not None and 0 < slt_i < 32767

            # Detect Practice (no end → both columns degrade gracefully)
            is_practice = False
            try:
                _si = core.sg("SessionInfo", None) or {}
                _csn = int(core.sg("SessionNum", 0) or 0)
                _sessions = _si.get("Sessions") if isinstance(_si, dict) else None
                if isinstance(_sessions, list) and 0 <= _csn < len(_sessions):
                    _stype = str((_sessions[_csn] or {}).get("SessionType", "") or "").lower()
                    if "practice" in _stype:
                        is_practice = True
            except Exception:
                pass

            # ---- Player lap data ----
            pi = core.player_idx()
            lapc = core.sg("CarIdxLapCompleted", []) or []
            cur_lap = 0
            try:
                if isinstance(pi, int) and 0 <= pi < len(lapc):
                    cur_lap = max(0, int(lapc[pi]))
            except Exception:
                cur_lap = 0

            # ---- Compute expected_player (for the LAPS cell) ----
            # Mirrors fuel.py's logic — leader-projection with class scaling.
            # expected_player = None
            # try:
            #     ... pace-ratio projection removed; Fuel and Info share build_finish_projection.
            # except Exception:
            #     expected_player = None
            expected_player = None  # 261001_CURSOR
            try:  # 261001_CURSOR
                dm = core.driver_map()  # 261001_CURSOR
                race_session = False  # 261001_CURSOR
                try:  # 261001_CURSOR
                    _si_lap = core.sg("SessionInfo", None) or {}  # 261001_CURSOR
                    _csn_lap = int(core.sg("SessionNum", 0) or 0)  # 261001_CURSOR
                    _sessions_lap = _si_lap.get("Sessions") if isinstance(_si_lap, dict) else None  # 261001_CURSOR
                    if isinstance(_sessions_lap, list) and 0 <= _csn_lap < len(_sessions_lap):  # 261001_CURSOR
                        _stype_lap = str((_sessions_lap[_csn_lap] or {}).get("SessionType", "") or "").lower()  # 261001_CURSOR
                        race_session = "race" in _stype_lap  # 261001_CURSOR
                except Exception:  # 261001_CURSOR
                    race_session = False  # 261001_CURSOR
                finish = build_finish_projection(  # 261001_CURSOR
                    player_idx=pi,  # 261001_CURSOR
                    player_completed=cur_lap,  # 261001_CURSOR
                    drivers=dm,  # 261001_CURSOR
                    lap_completed=core.sg("CarIdxLapCompleted", []) or [],  # 261001_CURSOR
                    lap_dist=core.sg("CarIdxLapDistPct", []) or [],  # 261001_CURSOR
                    positions=core.sg("CarIdxPosition", []) or [],  # 261001_CURSOR
                    surfaces=core.sg("CarIdxTrackSurface", []) or [],  # 261001_CURSOR
                    estimates=core.sg("CarIdxEstTime", []) or [],  # 261001_CURSOR
                    last_laps=core.sg("CarIdxLastLapTime", []) or [],  # 261001_CURSOR
                    best_laps=core.sg("CarIdxBestLapTime", []) or [],  # 261001_CURSOR
                    car_flags=core.sg("CarIdxSessionFlags", []) or [],  # 261001_CURSOR
                    time_remaining=core.sg("SessionTimeRemain", None),  # 261001_CURSOR
                    total_laps=slt,  # 261001_CURSOR
                    laps_remaining=core.sg("SessionLapsRemainEx", None),  # 261001_CURSOR
                    session_state=core.sg("SessionState", 0),  # 261001_CURSOR
                    is_practice=not race_session,  # 261001_CURSOR
                    checkered_finish_lap=self._checkered_finish_lap,  # 261001_CURSOR
                    average_pace=lambda idx: core.avg_sec_filtered(idx, 3, 8.0),  # 261001_CURSOR
                    is_safety=core._is_safety_car,  # 261001_CURSOR
                )  # 261001_CURSOR
                self._checkered_finish_lap = finish.get("checkered_finish_lap")  # 261001_CURSOR
                projection = finish.get("projection") if isinstance(finish, dict) else None  # 261001_CURSOR
                if projection:  # 261001_CURSOR
                    expected_player = projection.get("finish_lap")  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                expected_player = None  # 261001_CURSOR

            # LAPS cell text:
            #   Always show progress only as "<cur>/<expected>".
            #   If expected is not available yet, keep the same shape.
            if expected_player is None or expected_player <= 0:
                laps_value = f"{cur_lap}/--"
            else:
                laps_value = f"{cur_lap}/{expected_player}"

            # ---- TIME cell ----
            # Time race  → SessionTimeRemain countdown
            # Lap race   → SessionTime elapsed (count up)
            # Practice   → SessionTime elapsed (count up — no end time)
            sess_time = core.sg("SessionTime", None)
            sess_time_remain = core.sg("SessionTimeRemain", None)
            try:
                sess_time = float(sess_time) if sess_time is not None else None
            except Exception:
                sess_time = None
            try:
                sess_time_remain = float(sess_time_remain) if sess_time_remain is not None else None
            except Exception:
                sess_time_remain = None

            time_str = "—"
            time_mode = "elapsed"
            if is_practice:
                time_str = _fmt_mmss(sess_time)
                time_mode = "elapsed"
            elif is_lap_race:
                time_str = _fmt_mmss(sess_time)
                time_mode = "elapsed"
            else:
                # Time race — show countdown, but if remain is unset/sentinel
                # fall back to elapsed.
                if sess_time_remain is not None and 0 <= sess_time_remain < 1e7:
                    time_str = _fmt_mmss(sess_time_remain)
                    time_mode = "remaining"
                else:
                    time_str = _fmt_mmss(sess_time)
                    time_mode = "elapsed"

            # ---- Sim time of day (HH:MM) ----
            # SessionTimeOfDay is the in-sim wall-clock — seconds since
            # midnight in the simulated time zone. For most races this is
            # the visual cue for sun position and night driving.
            sim_tod = core.sg("SessionTimeOfDay", None)
            sim_str = "—"
            try:
                if sim_tod is not None:
                    s = float(sim_tod) % 86400.0
                    h = int(s // 3600)
                    m = int((s - h * 3600) // 60)
                    sim_str = f"{h:02d}:{m:02d}"
            except Exception:
                sim_str = "—"

            # ---- Real time (computer wall clock, HH:MM) ----
            try:
                lt = _wallclock.localtime()
                real_str = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
            except Exception:
                real_str = "—"

            # ---- INC (current / penalty-limit) ----
            # Format: "INC 7-17" → 7 incidents accrued, penalty kicks in at 17.
            #
            # iRacing's WeekendOptions actually exposes BOTH thresholds:
            #     IncidentWarningInitialLimit   = PENALTY threshold (the
            #                                     value the user wants —
            #                                     drive-through / end-of-
            #                                     session warning is issued)
            #     IncidentLimit                 = DQ threshold (final cap;
            #                                     car removed from results)
            # Verified across capture files:
            #     Oschersleben daily:   Penalty=17, DQ=25
            #     Nurburgring 24h:      Penalty=100, DQ=255
            #     Oulton (no warning):  Penalty=unlimited, DQ=17
            #     Talladega fun race:   Penalty=unlimited, DQ=unlimited
            #
            # Logic: use IncidentWarningInitialLimit when it's a real number;
            # otherwise fall back to IncidentLimit (some series have NO
            # warning step — IncidentLimit IS the only threshold and that
            # IS the penalty for those series). When everything is
            # "unlimited" (fun races), don't show a limit at all.
            inc_cur = core.sg("PlayerCarTeamIncidentCount", None)
            if inc_cur is None:
                inc_cur = core.sg("PlayerCarMyIncidentCount", None)
            if inc_cur is None:
                inc_cur = core.sg("PlayerCarDriverIncidentCount", None)
            try:
                inc_cur = int(inc_cur) if inc_cur is not None else None
            except Exception:
                inc_cur = None

            def _to_int_or_none(raw):
                """Return int(raw) if raw is a real number, None otherwise
                (covers 'unlimited' string, missing keys, etc.)."""
                if raw is None:
                    return None
                if isinstance(raw, str) and raw.strip().lower() == "unlimited":
                    return None
                try:
                    return int(raw)
                except Exception:
                    return None

            warn_limit = None
            dq_limit = None
            try:
                _wi = core.sg("WeekendInfo", None) or {}
                _wo = _wi.get("WeekendOptions") if isinstance(_wi, dict) else None
                if isinstance(_wo, dict):
                    warn_limit = _to_int_or_none(_wo.get("IncidentWarningInitialLimit"))
                    dq_limit   = _to_int_or_none(_wo.get("IncidentLimit"))
            except Exception:
                pass

            # Penalty (what we display): warning-limit when present,
            # else fall back to the DQ limit (that IS the penalty for
            # series with no warning step).
            inc_limit = warn_limit if warn_limit is not None else dq_limit

            if inc_cur is None:
                inc_str = "—"
            elif inc_limit is None:
                # Truly unlimited — show the count alone
                inc_str = f"{inc_cur}"
            else:
                inc_str = f"{inc_cur}-{inc_limit}"

            self._last_payload = {
                "current_lap":   cur_lap,
                "expected_laps": expected_player,
                "is_lap_race":   is_lap_race,
                "is_practice":   is_practice,
                "time_mode":     time_mode,
                "time_str":      time_str,
                "sim_str":       sim_str,
                "real_str":      real_str,
                "inc_cur":         inc_cur,
                "inc_limit":       inc_limit,
                "inc_warn_limit":  warn_limit,   # IncidentWarningInitialLimit
                "inc_dq_limit":    dq_limit,     # IncidentLimit
                "inc_str":         inc_str,
                "session_time":  sess_time,
                "session_time_remain": sess_time_remain,
            }
            core.update_state_and_debug_dump(extra={"info": self._last_payload})

            col_lookup = self._column_lookup()
            def _t(cid, value, color=core.CLR_WHITE):
                cfg = col_lookup.get(cid) or {}
                lbl = cfg.get("label", cid.upper())
                if cid == "laps":
                    return (cid, str(value), color)
                return (cid, f"{lbl} {value}" if lbl else str(value), color)

            cells = [
                _t("laps",     laps_value),
                _t("time",     time_str),
                _t("simtime",  sim_str),
                _t("realtime", real_str),
                _t("inc",      inc_str),
            ]
            self._draw_row(p, cells)

        except Exception as ex:
            core._log(f"Info paint error: {ex!r}")
            core._log(traceback.format_exc())
