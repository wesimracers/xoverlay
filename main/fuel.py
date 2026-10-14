# fuel
from PyQt6.QtGui import QPainter, QColor
from PyQt6.QtCore import Qt, QRect
from collections import deque
import traceback
from base import RowBar
import core
# from fuel_projection import project_finish, fuel_required, refuel_display, number, positive, lap_limit
from fuel_projection import fuel_required, refuel_display, number, positive, lap_limit, build_finish_projection  # 261001_CURSOR

# Default column layout — width-adjustable like standings/relative.
# The standalone LAPS column was removed in this revision: its information
# (laps remaining + cur/exp) is now packed into the FUEL cell so all the
# fuel-on-track context lives in one place.
_DEFAULT_COLUMNS = [
    {"id": "last",   "label": "LAST", "width": 80,  "enabled": True},
    {"id": "avg",    "label": "AVG",  "width": 80,  "enabled": True},
    {"id": "fuel",   "label": "F",    "width": 180, "enabled": True},
    {"id": "cons",   "label": "C",    "width": 60,  "enabled": True},
    {"id": "refuel", "label": "R",    "width": 70,  "enabled": True},
]


class Fuel(RowBar):
    def __init__(self):
        super().__init__("fuel", "fuel_settings", _DEFAULT_COLUMNS)
        fs = core.cfg.get("fuel_settings") or {}

        self.avg_window = int(fs.get("avg_window_laps", 5))
        self.max_lap_fuel = float(fs.get("max_lap_fuel", 50.0))
        self.reserve = float(fs.get("reserve_liters", 0.5))
        self.extra_pct = float(fs.get("extra_consumption_pct", 0.0))
        self.percentile = int(fs.get("consumption_percentile", 50))

        self.last_fuel = None
        self.last_lap = None
        self.hist = deque(maxlen=20)
        self.last_laptime = None
        # Total fuel consumed since session reset/join, integrated live from
        # fuel-level drops (refuels never subtract this counter).
        self.cons_total = 0.0
        # Previous-frame fuel sample for live consumption integration.
        self._cons_prev_fuel = None
        self._last_payload = {}
        self._last_sig = None
        self._last_reset_epoch = 0
        # Track pit-during-lap: True if the player was on pit road at ANY
        # point during the current lap. We can't trust the S/F-crossing
        # snapshot alone because the player might re-emerge on track well
        # before crossing the line, fooling `onpit_list[pi]` into False
        # right when we compute `used`. That makes pit-stop laps look like
        # genuine super-low-consumption laps — which would tank AVG and
        # mislead REFUEL planning. We watch every frame instead.
        self._pit_visited_this_lap = False
        # First-observation gate: if our very first paint catches the
        # player mid-lap (LapDistPct > 0.1), the first "lap completed"
        # event captures only a partial-lap consumption — discard it.
        self._first_lap_seen = False
        self._invalid_this_lap = False
        self._lap_inc_start = 0
        self._last_lap_raw_used = None
        self._last_lap_reject_reason = ""
        self._checkered_finish_lap = None
        self._fuel_now = 0.0  # 261001_CURSOR
        self._pi = 0  # 261001_CURSOR
        self._lapc = None  # 261001_CURSOR
        self._inc_now = 0  # 261001_CURSOR
        self._session_flags = 0  # 261001_CURSOR

    def reset_state(self):
        self.last_fuel = None
        self.last_lap = None
        self.hist.clear()
        self.last_laptime = None
        self.cons_total = 0.0
        self._cons_prev_fuel = None
        self._last_payload = {}
        self._pit_visited_this_lap = False
        self._first_lap_seen = False
        self._invalid_this_lap = False
        self._lap_inc_start = 0
        self._last_lap_raw_used = None
        self._last_lap_reject_reason = ""
        self._checkered_finish_lap = None

    def _percentile(self, data, p):
        if not data:
            return None
        data = sorted(data)
        k = int(round((p / 100.0) * (len(data) - 1)))
        return data[k]

    def _power_weighted_max(self, data, exponent=4):
        """Power-weighted mean — each lap's weight is `value ** exponent`.
        Higher-consumption laps dominate the result. Used for REFUEL
        planning so we ASSUME a worst-case-ish consumption and don't
        risk running out mid-final-stint.

        Example with [1.0, 2.0, 2.5, 2.4, 2.3]:
          plain mean         = 2.04
          power-weighted^4   = 2.34  (close to max, but smoothed)
          max                = 2.50

        Exponent 4 chosen as a good balance: an outlier ~30% above the
        norm pulls the result ~15% higher (defensive enough to cover a
        bad stint, not so heavy that one fluke lap dominates the plan)."""
        if not data:
            return None
        if len(data) == 1:
            return data[0]
        try:
            weights = [(float(v) ** exponent) if v > 0 else 0.0 for v in data]
            total_w = sum(weights)
            if total_w <= 0:
                return None
            return sum(float(v) * w for v, w in zip(data, weights)) / total_w
        except Exception:
            return None

    def _player_incident_count(self):
        total = 0
        for name in ("PlayerCarMyIncidentCount",
                     "PlayerCarTeamIncidentCount",
                     "PlayerCarDriverIncidentCount"):
            try:
                v = int(float(core.sg(name, 0) or 0))
                if v > total:
                    total = v
            except Exception:
                pass
        return total

    def _fuel_invalid_flags(self):
        try:
            flags = int(core.sg("SessionFlags", 0) or 0)
        except Exception:
            flags = 0
        # Reject full-course caution laps. Local yellow/black/repair flags
        # do not make the measured fuel burn invalid and previously caused
        # long stretches with AVG stuck at zero.
        bad_mask = 0x00000200 | 0x00004000 | 0x00008000
        return flags, bool(flags & bad_mask)

    def sample_fast(self):  # 261001_CURSOR
        try:  # 261001_CURSOR
            if not core.connect():  # 261001_CURSOR
                return  # 261001_CURSOR
            try:  # 261001_CURSOR
                core.ir.freeze_var_buffer_latest()  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                pass  # 261001_CURSOR
            if core.is_in_reset_grace():  # 261001_CURSOR
                self.reset_state()  # 261001_CURSOR
                try:  # 261001_CURSOR
                    self._last_sig = core._SESSION_SIG[0]  # 261001_CURSOR
                    self._last_reset_epoch = core._RESET_EPOCH[0]  # 261001_CURSOR
                except Exception:  # 261001_CURSOR
                    pass  # 261001_CURSOR
                return  # 261001_CURSOR
            self._advance_fuel_state()  # 261001_CURSOR
        except Exception as ex:  # 261001_CURSOR
            core._log(f"Fuel sample error: {ex!r}")  # 261001_CURSOR

    def _advance_fuel_state(self):  # 261001_CURSOR
        try:  # 261001_CURSOR
            _cur_sig = core._SESSION_SIG[0]  # 261001_CURSOR
            _cur_epoch = core._RESET_EPOCH[0]  # 261001_CURSOR
            if _cur_sig != self._last_sig or _cur_epoch != self._last_reset_epoch:  # 261001_CURSOR
                self.reset_state()  # 261001_CURSOR
                self._last_sig = _cur_sig  # 261001_CURSOR
                self._last_reset_epoch = _cur_epoch  # 261001_CURSOR
        except Exception:  # 261001_CURSOR
            pass  # 261001_CURSOR
        fuel = float(core.sg("FuelLevel", 0.0) or 0.0)  # 261001_CURSOR
        lap_list = core.sg("CarIdxLapCompleted", [])  # 261001_CURSOR
        pi = core.player_idx()  # 261001_CURSOR
        try:  # 261001_CURSOR
            lapc = int(lap_list[pi]) if lap_list and len(lap_list) > pi else None  # 261001_CURSOR
        except Exception:  # 261001_CURSOR
            lapc = None  # 261001_CURSOR
        self._fuel_now = fuel  # 261001_CURSOR
        self._pi = pi  # 261001_CURSOR
        self._lapc = lapc  # 261001_CURSOR
        if lapc is None or lapc < 0:  # 261001_CURSOR
            self.reset_state()  # 261001_CURSOR
            self._last_payload = {"inactive": True, "reason": "player_not_live"}  # 261001_CURSOR
            core.update_state_and_debug_dump(extra={"fuel": self._last_payload})  # 261001_CURSOR
            return "inactive"  # 261001_CURSOR
        lastlt = core.sg("CarIdxLastLapTime", [])  # 261001_CURSOR
        if lastlt and len(lastlt) > pi:  # 261001_CURSOR
            try:  # 261001_CURSOR
                v = float(lastlt[pi])  # 261001_CURSOR
                if v > 0:  # 261001_CURSOR
                    self.last_laptime = v  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                pass  # 261001_CURSOR
        if self._cons_prev_fuel is None:  # 261001_CURSOR
            self._cons_prev_fuel = fuel  # 261001_CURSOR
        else:  # 261001_CURSOR
            try:  # 261001_CURSOR
                burn = float(self._cons_prev_fuel) - float(fuel)  # 261001_CURSOR
                if 0 < burn < self.max_lap_fuel:  # 261001_CURSOR
                    self.cons_total += burn  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                pass  # 261001_CURSOR
            self._cons_prev_fuel = fuel  # 261001_CURSOR
        onpit_list_now = core.sg("CarIdxOnPitRoad", [])  # 261001_CURSOR
        if onpit_list_now and len(onpit_list_now) > pi:  # 261001_CURSOR
            try:  # 261001_CURSOR
                if bool(onpit_list_now[pi]):  # 261001_CURSOR
                    self._pit_visited_this_lap = True  # 261001_CURSOR
                    self._invalid_this_lap = True  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                pass  # 261001_CURSOR
        flags, bad_flags = self._fuel_invalid_flags()  # 261001_CURSOR
        self._session_flags = flags  # 261001_CURSOR
        if bad_flags:  # 261001_CURSOR
            self._invalid_this_lap = True  # 261001_CURSOR
        inc_now = self._player_incident_count()  # 261001_CURSOR
        self._inc_now = inc_now  # 261001_CURSOR
        if self.last_fuel is None:  # 261001_CURSOR
            self.last_fuel = fuel  # 261001_CURSOR
            self.last_lap = lapc  # 261001_CURSOR
            self._lap_inc_start = inc_now  # 261001_CURSOR
            try:  # 261001_CURSOR
                _dist_arr = core.sg("CarIdxLapDistPct", [])  # 261001_CURSOR
                _start_dp = float(_dist_arr[pi]) if _dist_arr and len(_dist_arr) > pi else 0.0  # 261001_CURSOR
                self._first_lap_seen = (0.0 <= _start_dp <= 0.001)  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                self._first_lap_seen = False  # 261001_CURSOR
        elif lapc is not None and self.last_lap is not None and lapc > self.last_lap:  # 261001_CURSOR
            used = self.last_fuel - fuel  # 261001_CURSOR
            self._last_lap_raw_used = used  # 261001_CURSOR
            reject_reason = ""  # 261001_CURSOR
            if lapc != self.last_lap + 1:  # 261001_CURSOR
                reject_reason = "skipped_laps"  # 261001_CURSOR
            elif not self._first_lap_seen:  # 261001_CURSOR
                reject_reason = "partial_first_lap"  # 261001_CURSOR
            elif self._pit_visited_this_lap:  # 261001_CURSOR
                reject_reason = "pit_or_refuel"  # 261001_CURSOR
            elif self._invalid_this_lap:  # 261001_CURSOR
                reject_reason = "full_course_caution"  # 261001_CURSOR
            elif used <= 0:  # 261001_CURSOR
                reject_reason = "refuel_or_no_drop"  # 261001_CURSOR
            elif used >= self.max_lap_fuel:  # 261001_CURSOR
                reject_reason = "over_max_lap_fuel"  # 261001_CURSOR
            if not reject_reason:  # 261001_CURSOR
                self.hist.append(used)  # 261001_CURSOR
            self._last_lap_reject_reason = reject_reason  # 261001_CURSOR
            self._first_lap_seen = True  # 261001_CURSOR
            self._pit_visited_this_lap = False  # 261001_CURSOR
            self._invalid_this_lap = False  # 261001_CURSOR
            self._lap_inc_start = inc_now  # 261001_CURSOR
            self.last_fuel = fuel  # 261001_CURSOR
            self.last_lap = lapc  # 261001_CURSOR
        return "ok"  # 261001_CURSOR

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
            p.fillRect(self.rect(), QColor(0, 0, 0))
            p.setFont(self.font_normal)

            if not core.ir.is_connected:
                p.setPen(core.CLR_WHITE)
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y, self.width() - 2 * core.PAD_X, self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "FUEL: DISCONNECTED",
                )
                return

            # Reset-grace placeholder (see relative.py for full reasoning).
            if core.is_in_reset_grace():
                p.setFont(self.font_bold)
                p.setPen(QColor(255, 200, 0))
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y,
                          self.width() - 2 * core.PAD_X,
                          self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "FUEL: NEW SESSION…",
                )
                # Force the per-widget bookkeeping forward so the very next
                # post-grace paint starts from the right epoch.
                try:
                    self.reset_state()
                    self._last_sig = core._SESSION_SIG[0]
                    self._last_reset_epoch = core._RESET_EPOCH[0]
                except Exception:
                    pass
                return

#            # --- Session-change reset: wipe fuel history on new practice/qualify/race ---
#            # core._SESSION_SIG[0] flips when (SessionID, SessionNum, SessionType,
#            # TrackName) changes. Without this check, hist/last_fuel/last_laptime
#            # carry over from the previous session, showing stale LAST/AVG/LAPS.
#            try:
#                _cur_sig = core._SESSION_SIG[0]
#                _cur_epoch = core._RESET_EPOCH[0]
#                if _cur_sig != self._last_sig or _cur_epoch != self._last_reset_epoch:
#                    self.reset_state()
#                    self._last_sig = _cur_sig
#                    self._last_reset_epoch = _cur_epoch
#            except Exception:
#                pass
#
#            fuel = float(core.sg("FuelLevel", 0.0) or 0.0)
#
#            # lapc = core.sg("LapCompleted", None)
#            # try:
#            #     lapc = int(lapc)
#            # except Exception:
#            #     lapc = None
#
#            lap_list = core.sg("CarIdxLapCompleted", [])
#            pi = core.player_idx()
#            try:
#                lapc = int(lap_list[pi]) if lap_list and len(lap_list) > pi else None
#            except Exception:
#                lapc = None
#
#            # During session transitions iRacing can report lap=-1 / not-live
#            # with stale fuel. Keep F reset/blank until player is valid again.
#            if lapc is None or lapc < 0:
#                self.reset_state()
#                self._last_payload = {
#                    "inactive": True,
#                    "reason": "player_not_live",
#                }
#                core.update_state_and_debug_dump(extra={"fuel": self._last_payload})
#                col_lookup = self._column_lookup()
#                def _t(cid, value, color=core.CLR_WHITE):
#                    cfg = col_lookup.get(cid) or {}
#                    lbl = cfg.get("label", cid.upper())
#                    return (cid, f"{lbl} {value}" if lbl else str(value), color)
#                self._draw_row(p, [
#                    _t("last", "0.00"),
#                    _t("avg", "0.00"),
#                    _t("fuel", "--"),
#                    _t("cons", "0"),
#                    _t("refuel", "—", core.CLR_WHITE),
#                ])
#                return
#
#            pi = core.player_idx()
#
#            lastlt = core.sg("CarIdxLastLapTime", [])
#            if lastlt and len(lastlt) > pi:
#                try:
#                    v = float(lastlt[pi])
#                    if v > 0:
#                        self.last_laptime = v
#                except Exception:
#                    pass
#
#            # Live cumulative consumption since joining the car:
#            # add only positive fuel drops; refuels (fuel rise) don't subtract.
#            if self._cons_prev_fuel is None:
#                self._cons_prev_fuel = fuel
#            else:
#                try:
#                    burn = float(self._cons_prev_fuel) - float(fuel)
#                    if 0 < burn < self.max_lap_fuel:
#                        self.cons_total += burn
#                except Exception:
#                    pass
#                self._cons_prev_fuel = fuel
#
#            # -------- detect lap consumption --------
#            # Track whether a lap just completed THIS frame — used below to
#            # decide which cells should freshly compute their display value.
#            # The user's rule (this rev): all FUEL cells except the FUEL one
#            # itself (which carries live current-fuel + remaining-laps inside
#            # parens) should only update when the player crosses S/F.
#
#            # Watch pit road every frame so a pit stop ANYWHERE during the
#            # lap disqualifies that lap from hist. Reading the on-pit flag
#            # only at S/F-crossing time misses cases where the player has
#            # already left the pit lane by the time they cross the line —
#            # the resulting "low consumption" would silently tank AVG and
#            # make REFUEL planning recommend too little fuel.
#            onpit_list_now = core.sg("CarIdxOnPitRoad", [])
#            if onpit_list_now and len(onpit_list_now) > pi:
#                try:
#                    if bool(onpit_list_now[pi]):
#                        self._pit_visited_this_lap = True
#                        self._invalid_this_lap = True
#                except Exception:
#                    pass
#
#            flags, bad_flags = self._fuel_invalid_flags()
#            if bad_flags:
#                self._invalid_this_lap = True
#
#            inc_now = self._player_incident_count()
#
#            lap_just_completed = False
#            if self.last_fuel is None:
#                self.last_fuel = fuel
#                self.last_lap = lapc
#                self._lap_inc_start = inc_now
#                # Snap whether we joined mid-lap. If we did, the FIRST
#                # "lap completed" event has only partial-lap consumption
#                # captured in `used` and must be discarded.
#                try:
#                    _dist_arr = core.sg("CarIdxLapDistPct", [])
#                    _start_dp = float(_dist_arr[pi]) if _dist_arr and len(_dist_arr) > pi else 0.0
#                    # Only a start/finish anchor measures a full lap. A join
#                    # even 5% into the lap must not lower measured consumption.
#                    self._first_lap_seen = (0.0 <= _start_dp <= 0.001)
#                except Exception:
#                    self._first_lap_seen = False
#            else:
#                if lapc is not None and self.last_lap is not None and lapc > self.last_lap:
#                    used = self.last_fuel - fuel
#                    self._last_lap_raw_used = used
#                    reject_reason = ""
#                    if lapc != self.last_lap + 1:
#                        reject_reason = "skipped_laps"
#                    elif not self._first_lap_seen:
#                        reject_reason = "partial_first_lap"
#                    elif self._pit_visited_this_lap:
#                        reject_reason = "pit_or_refuel"
#                    elif self._invalid_this_lap:
#                        reject_reason = "full_course_caution"
#                    elif used <= 0:
#                        reject_reason = "refuel_or_no_drop"
#                    elif used >= self.max_lap_fuel:
#                        reject_reason = "over_max_lap_fuel"
#
#                    if not reject_reason:
#                        self.hist.append(used)
#                    self._last_lap_reject_reason = reject_reason
#
#                    # After the first S/F crossing the rest are genuine
#                    # full-lap measurements — flip the gate on.
#                    self._first_lap_seen = True
#                    # Pit flag resets each lap.
#                    self._pit_visited_this_lap = False
#                    self._invalid_this_lap = False
#                    self._lap_inc_start = inc_now
#
#                    self.last_fuel = fuel
#                    self.last_lap = lapc
#                    lap_just_completed = True
            status = self._advance_fuel_state()  # 261001_CURSOR
            if status == "inactive":  # 261001_CURSOR
                col_lookup = self._column_lookup()  # 261001_CURSOR
                def _t(cid, value, color=core.CLR_WHITE):  # 261001_CURSOR
                    cfg = col_lookup.get(cid) or {}  # 261001_CURSOR
                    lbl = cfg.get("label", cid.upper())  # 261001_CURSOR
                    return (cid, f"{lbl} {value}" if lbl else str(value), color)  # 261001_CURSOR
                self._draw_row(p, [  # 261001_CURSOR
                    _t("last", "0.00"),  # 261001_CURSOR
                    _t("avg", "0.00"),  # 261001_CURSOR
                    _t("fuel", "--"),  # 261001_CURSOR
                    _t("cons", "0"),  # 261001_CURSOR
                    _t("refuel", "\u2014", core.CLR_WHITE),  # 261001_CURSOR
                ])  # 261001_CURSOR
                return  # 261001_CURSOR
            fuel = self._fuel_now  # 261001_CURSOR
            pi = self._pi  # 261001_CURSOR
            lapc = self._lapc  # 261001_CURSOR
            inc_now = self._inc_now  # 261001_CURSOR
            flags = self._session_flags  # 261001_CURSOR


            last_used = self.hist[-1] if self.hist else 0.0

            # -------- compute consumption --------
            # ---- AVG (for display + laps-remaining estimate) ----
            # Percentile-based smoothed value across the avg_window. This
            # is what the AVG cell displays and what the laps-remaining
            # readout uses to estimate "how many laps of fuel I have".
            # We accept even a single clean lap (relaxed from `>= 2`) so
            # AVG isn't stuck at 0.00 for the entire first stint — the
            # percentile fn handles n=1 correctly (returns that single
            # value), and a one-lap estimate is far more useful than no
            # estimate at all.
            avg = None
            if len(self.hist) >= 1:
                recent = list(self.hist)[-self.avg_window :]
                base = self._percentile(recent, self.percentile)
                if base:
                    avg = base * (1 + self.extra_pct / 100.0)

            avg_disp = float(avg) if (avg and avg > 0) else 0.0

            # ---- REFUEL-planning consumption (POWER-WEIGHTED MAX) ----
            # The REFUEL cell uses a DIFFERENT smoothing: a power-weighted
            # mean across ALL prior clean laps (not just the avg_window),
            # with exponent 4. This biases heavily toward the WORST recent
            # laps so the recommended refuel amount stays defensive — the
            # user explicitly asked: "higher consumption per lap have more
            # importance than the lower consumption per lap" so the plan
            # doesn't risk being short of fuel from a few unlucky stints.
            # All-history (not just window) so a clean fast lap can't
            # forget about the heavier stop-and-go laps earlier in race.
            avg_refuel = None
            if len(self.hist) >= 1:
                avg_refuel = self._power_weighted_max(list(self.hist), exponent=4)
                if avg_refuel:
                    avg_refuel = avg_refuel * (1 + self.extra_pct / 100.0)
            if avg_refuel is None:
                # Early race or no history yet — fall back to display avg
                avg_refuel = avg_disp

            # -------- remaining laps (safe fuel) --------
            fuel_safe = max(0.0, fuel - self.reserve)
            laps_remaining = (fuel_safe / avg_disp) if avg_disp > 0 else 0.0

            # Project a finish-line crossing, then use that SAME remaining
            # distance for fuel. Timer expiry itself is never the finish.
            sess_time_remain = number(core.sg("SessionTimeRemain", None))
            cur_lap = int(lapc)
            expected_txt = ""
            expected_player = None
            projection = None
            refuel_needed = None
            dm = core.driver_map()
            lap_arr = core.sg("CarIdxLapCompleted", []) or []
            dist_arr = core.sg("CarIdxLapDistPct", []) or []
            position_arr = core.sg("CarIdxPosition", []) or []
            surface_arr = core.sg("CarIdxTrackSurface", []) or []
            est_arr = core.sg("CarIdxEstTime", []) or []
            lastlt_arr = core.sg("CarIdxLastLapTime", []) or []
            bestlt_arr = core.sg("CarIdxBestLapTime", []) or []
            car_flags = core.sg("CarIdxSessionFlags", []) or []
            _payload_slt = core.sg("SessionLapsTotal", None)
            _payload_slr = core.sg("SessionLapsRemainEx", None)
            is_lap_race = lap_limit(_payload_slt) is not None
            sessions = (core.sg("SessionInfo", {}) or {}).get("Sessions", [])
            session_num = int(core.sg("SessionNum", 0) or 0)
            stype = str(sessions[session_num].get("SessionType", "")) if 0 <= session_num < len(sessions) else ""
            is_practice = "race" not in stype.lower()
            state = int(core.sg("SessionState", 0) or 0)

            # def value(values, idx, default=None):
            #     return values[idx] if isinstance(idx, int) and 0 <= idx < len(values) else default
            #
            # def pace(idx):
            #     best = positive(value(bestlt_arr, idx))
            #     last = positive(value(lastlt_arr, idx))
            #     average = positive(core.avg_sec_filtered(idx, 3, 8.0))
            #     if average:
            #         return average
            #     if last and (best is None or last <= best * 1.15):
            #         return last
            #     return best or positive(dm.get(idx, {}).get("CarClassEstLapTime"))
            #
            # def phase(idx):
            #     estimate = number(value(est_arr, idx))
            #     model_lap = positive(dm.get(idx, {}).get("CarClassEstLapTime"))
            #     if estimate is not None and model_lap and 0 < estimate <= model_lap:
            #         return estimate / model_lap
            #     return None
            #
            # active = []
            # for idx, driver in dm.items():
            #     lc = number(value(lap_arr, idx))
            #     dp = number(value(dist_arr, idx))
            #     surface = number(value(surface_arr, idx))
            #     if (core._is_safety_car(driver) or lc is None or lc < 0 or
            #             dp is None or not 0 <= dp <= 1 or
            #             (surface is not None and surface < 0)):
            #         continue
            #     active.append(idx)
            # leader_idx = next((idx for idx in active if value(position_arr, idx) == 1), None)
            # if leader_idx is None and active:
            #     leader_idx = max(active, key=lambda idx: lap_arr[idx] + dist_arr[idx])
            # player_dp = number(value(dist_arr, pi))
            # player_flags = int(value(car_flags, pi, 0) or 0)
            # player_finished = bool(player_flags & 0x1) or state >= 6
            # leader_finished = state == 5
            # if leader_finished and self._checkered_finish_lap is None:
            #     self._checkered_finish_lap = cur_lap + 1
            # if self._checkered_finish_lap is not None and cur_lap >= self._checkered_finish_lap:
            #     player_finished = True
            #
            # if not is_practice and leader_idx is not None:
            #     projection = project_finish(
            #         player_completed=cur_lap, player_position=player_dp,
            #         player_lap_time=pace(pi), leader_completed=value(lap_arr, leader_idx),
            #         leader_position=value(dist_arr, leader_idx), leader_lap_time=pace(leader_idx),
            #         time_remaining=sess_time_remain, total_laps=_payload_slt,
            #         laps_remaining=_payload_slr, player_phase=phase(pi), leader_phase=phase(leader_idx),
            #         leader_finished=leader_finished, player_finished=player_finished,
            #         player_white=bool(player_flags & 0x2),
            #         same_class=dm.get(pi, {}).get("CarClassID") == dm.get(leader_idx, {}).get("CarClassID"),
            #     )
            finish = build_finish_projection(  # 261001_CURSOR
                player_idx=pi,  # 261001_CURSOR
                player_completed=cur_lap,  # 261001_CURSOR
                drivers=dm,  # 261001_CURSOR
                lap_completed=lap_arr,  # 261001_CURSOR
                lap_dist=dist_arr,  # 261001_CURSOR
                positions=position_arr,  # 261001_CURSOR
                surfaces=surface_arr,  # 261001_CURSOR
                estimates=est_arr,  # 261001_CURSOR
                last_laps=lastlt_arr,  # 261001_CURSOR
                best_laps=bestlt_arr,  # 261001_CURSOR
                car_flags=car_flags,  # 261001_CURSOR
                time_remaining=sess_time_remain,  # 261001_CURSOR
                total_laps=_payload_slt,  # 261001_CURSOR
                laps_remaining=_payload_slr,  # 261001_CURSOR
                session_state=state,  # 261001_CURSOR
                is_practice=is_practice,  # 261001_CURSOR
                checkered_finish_lap=self._checkered_finish_lap,  # 261001_CURSOR
                average_pace=lambda idx: core.avg_sec_filtered(idx, 3, 8.0),  # 261001_CURSOR
                is_safety=core._is_safety_car,  # 261001_CURSOR
            )  # 261001_CURSOR
            self._checkered_finish_lap = finish["checkered_finish_lap"]  # 261001_CURSOR
            projection = finish["projection"]  # 261001_CURSOR
            player_dp = finish["player_dist"]  # 261001_CURSOR
            if projection is not None:
                expected_player = projection["finish_lap"]
                expected_txt = f" ({cur_lap}/{expected_player})"
                burned = None
                if (self._first_lap_seen and not self._pit_visited_this_lap and
                        not self._invalid_this_lap and self.last_fuel is not None):
                    burned = max(0.0, self.last_fuel - fuel)
                needed = fuel_required(projection["laps_left"], avg_refuel, self.reserve,
                                       position=player_dp, burned_this_lap=burned)
                if needed is not None:
                    refuel_needed = max(0.0, needed - fuel)
            refuel_col = (core.CLR_WHITE if refuel_needed is None else
                          core.CLR_GREEN if refuel_needed <= 0 else core.CLR_RED)

            self._last_payload = {
                "last_used": last_used,
                "avg": avg_disp,
                "avg_refuel": avg_refuel,
                "laps_remaining": laps_remaining,
                "refuel": refuel_needed,
                "finish_projection": projection,
                "race_laps_left": projection["laps_left"] if projection else None,
                "cons_total": self.cons_total,
                # --- Debug fields so captures can verify the (cur/exp) display ---
                "current_lap": cur_lap,
                "expected_laps": expected_player,       # None if not computable yet
                "expected_txt": expected_txt,           # exact string rendered (or "")
                "is_lap_race": is_lap_race,
                "is_practice": is_practice,
                "session_time_remain": sess_time_remain,
                "session_laps_total": _payload_slt,
                "session_laps_remain": _payload_slr,
                "invalid_this_lap": self._invalid_this_lap,
                "player_incidents": inc_now,
                "session_flags": flags,
                "accepted_lap_samples": len(self.hist),
                "last_lap_raw_used": self._last_lap_raw_used,
                "last_lap_reject_reason": self._last_lap_reject_reason,
            }

            core.update_state_and_debug_dump(extra={"fuel": self._last_payload})

            # ---- Column rendering ----
            col_lookup = self._column_lookup()
            def _t(cid, value, color=core.CLR_WHITE):
                cfg = col_lookup.get(cid) or {}
                lbl = cfg.get("label", cid.upper())
                return (cid, f"{lbl} {value}" if lbl else str(value), color)

            # FUEL cell: only current tank level + laps remaining.
            fuel_text = f"{fuel:.1f} ({laps_remaining:.1f})"
            cons_live_txt = f"{self.cons_total:.1f}"

            cells = [
                _t("last",   f"{last_used:.2f}"),
                _t("avg",    f"{avg_disp:.2f}"),
                _t("fuel",   fuel_text),
                _t("cons",   cons_live_txt),
                _t("refuel", refuel_display(refuel_needed), refuel_col),
            ]
            self._draw_row(p, cells)

        except Exception as ex:
            core._log(f"Fuel paint error: {ex!r}")
            core._log(traceback.format_exc())


# if correct reply yes, else return solutions that are mandatory to work
