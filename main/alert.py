# alert
#
# Closing-rate alert widget with configurable priority arbitration.
# Multiple conditions can be active at once (actual closing alert,
# yellow/caution, dirty track, blue flag). The widget flashes only the
# highest-priority active condition.

from PyQt6.QtGui import QPainter, QColor, QFont
from PyQt6.QtCore import Qt, QRect, QTimer
from collections import deque
import time as _time
import traceback

import core
from base import BaseWin
from relative_timing import RelativeTiming  # 261001_CURSOR


DEFAULT_RATE_THRESHOLD = 0.8
DEFAULT_GAP_MAX = 5.0
DEFAULT_HISTORY_S = 2.0
DEFAULT_FLASH_HZ = 4.0
DEFAULT_ACTIVATION_DELAY_S = 0.25

DEFAULT_PRIORITY_ALERT = 1
DEFAULT_PRIORITY_YELLOW = 2
DEFAULT_PRIORITY_DIRTY = 3
DEFAULT_PRIORITY_BLUE = 4

# iRacing SessionFlags bits
FLAG_YELLOW = 0x00000008
FLAG_BLUE = 0x00000020
FLAG_DEBRIS = 0x00000040
FLAG_YELLOW_WAVING = 0x00000100
FLAG_CAUTION = 0x00004000
FLAG_CAUTION_WAVING = 0x00008000


def _wrap_frac(d):
    while d > 0.5:
        d -= 1.0
    while d < -0.5:
        d += 1.0
    return d


class Alert(BaseWin):
    def __init__(self):
        super().__init__("alert")
        s = core.cfg.get("alert_settings") or {}

        self.rate_threshold = float(DEFAULT_RATE_THRESHOLD)
        self.gap_max = float(DEFAULT_GAP_MAX)
        self.history_s = float(DEFAULT_HISTORY_S)
        self.flash_hz = float(DEFAULT_FLASH_HZ)
        self.activation_delay_s = float(DEFAULT_ACTIVATION_DELAY_S)
        self.priority_alert = int(DEFAULT_PRIORITY_ALERT)
        self.priority_yellow = int(DEFAULT_PRIORITY_YELLOW)
        self.priority_dirty = int(DEFAULT_PRIORITY_DIRTY)
        self.priority_blue = int(DEFAULT_PRIORITY_BLUE)
        self.show_border = False

        # Set from manager while the config dialog is open so the user can
        # position this transparent widget.
        self._force_outline = False

        # Transparent background - alert is only visible when active.
        from PyQt6.QtCore import Qt as _Qt
        try:
            self.setAttribute(_Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAttribute(_Qt.WidgetAttribute.WA_NoSystemBackground, True)
        except Exception:
            pass

        # Per-car gap history: car_idx -> deque[(session_time, gap_sec)]
        self._gap_hist = {}
        self._last_payload = {}
        self._last_sig = None
        self._last_reset_epoch = 0
        self._active_mode = None
        self._active_since = 0.0
        self._timing = RelativeTiming()  # 261001_CURSOR

        # Continuous repaint drives flash cadence even if data tick is slower.
        self._paint_timer = QTimer(self)
        self._paint_timer.timeout.connect(self.update)
        self.apply_settings(s)
        self._paint_timer.start()

    def apply_settings(self, s: dict):
        try:
            self.rate_threshold = float(s.get("rate_threshold", DEFAULT_RATE_THRESHOLD))
        except Exception:
            self.rate_threshold = float(DEFAULT_RATE_THRESHOLD)
        try:
            self.gap_max = float(s.get("gap_max_sec", DEFAULT_GAP_MAX))
        except Exception:
            self.gap_max = float(DEFAULT_GAP_MAX)
        try:
            self.history_s = float(s.get("history_seconds", DEFAULT_HISTORY_S))
        except Exception:
            self.history_s = float(DEFAULT_HISTORY_S)
        try:
            self.flash_hz = float(s.get("flash_hz", DEFAULT_FLASH_HZ))
        except Exception:
            self.flash_hz = float(DEFAULT_FLASH_HZ)
        try:
            self.activation_delay_s = max(0.0, float(s.get("activation_delay_s", DEFAULT_ACTIVATION_DELAY_S)))
        except Exception:
            self.activation_delay_s = float(DEFAULT_ACTIVATION_DELAY_S)

        self.priority_alert = self._parse_priority(
            s.get("priority_alert", DEFAULT_PRIORITY_ALERT),
            DEFAULT_PRIORITY_ALERT,
        )
        self.priority_yellow = self._parse_priority(
            s.get("priority_yellow", DEFAULT_PRIORITY_YELLOW),
            DEFAULT_PRIORITY_YELLOW,
        )
        self.priority_dirty = self._parse_priority(
            s.get("priority_dirty", DEFAULT_PRIORITY_DIRTY),
            DEFAULT_PRIORITY_DIRTY,
        )
        self.priority_blue = self._parse_priority(
            s.get("priority_blue", DEFAULT_PRIORITY_BLUE),
            DEFAULT_PRIORITY_BLUE,
        )
        self.show_border = bool(s.get("show_border", False))

        try:
            self._paint_timer.setInterval(int(1000.0 / max(2.0, self.flash_hz * 2.0)))
        except Exception:
            pass
        self.update()

    @staticmethod
    def _parse_priority(val, fallback):
        try:
            p = int(val)
            return p if p > 0 else int(fallback)
        except Exception:
            return int(fallback)

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        # Sample once per data tick; paint timer handles flash redraw.
        self._sample_gaps()
        self.update()

    # -- gap computation --------------------------------------------------

    def _gap_to(self, player_dp, opp_dp, player_lt):
        """Signed time gap (positive = opp ahead on track)."""
        try:
            d = core.ref_lap_delta(player_dp, opp_dp) if hasattr(core, "ref_lap_delta") else None
            if d is not None:
                return d
        except Exception:
            pass
        try:
            dd = _wrap_frac(opp_dp - player_dp)
            return dd * float(player_lt or 90.0)
        except Exception:
            return None

    def _sample_gaps(self):
        """Read telemetry and update per-car (t, gap) deques."""
        try:
            # Session-reset wipe
            try:
                _cur_sig = core._SESSION_SIG[0]
                _cur_epoch = core._RESET_EPOCH[0]
                if _cur_sig != self._last_sig or _cur_epoch != self._last_reset_epoch:
                    self._gap_hist.clear()
                    self._timing.reset()  # 261001_CURSOR
                    self._last_sig = _cur_sig
                    self._last_reset_epoch = _cur_epoch
            except Exception:
                pass

            if not getattr(core.ir, "is_connected", False):
                self._gap_hist.clear()
                self._timing.reset()  # 261001_CURSOR
                return

            pi = core.player_idx()
            dp_arr = core.sg("CarIdxLapDistPct", []) or []
            op_arr = core.sg("CarIdxOnPitRoad", []) or []
            if pi is None or pi < 0 or pi >= len(dp_arr):
                return
            try:
                pdp = float(dp_arr[pi])
            except Exception:
                return
            if pdp < 0:
                return
            player_pit = bool(op_arr[pi]) if pi < len(op_arr) else False
            if player_pit:
                self._gap_hist.clear()
                return

            # Suppress false positives in caution and low-speed contexts.
            try:
                _flags = int(core.sg("SessionFlags", 0) or 0)
                if _flags & FLAG_CAUTION or _flags & FLAG_CAUTION_WAVING:
                    self._gap_hist.clear()
                    return
            except Exception:
                pass

            try:
                _spd = float(core.sg("Speed", 0.0) or 0.0)
                if _spd < 25.0:
                    self._gap_hist.clear()
                    return
            except Exception:
                pass

            player_lt = None
            try:
                player_lt = core.avg_sec(pi, 3)
            except Exception:
                pass
            if not player_lt or player_lt < 20:
                try:
                    bst = core.sg("CarIdxBestLapTime", []) or []
                    if pi < len(bst) and bst[pi] > 20:
                        player_lt = float(bst[pi])
                except Exception:
                    pass
            if not player_lt or player_lt < 20:
                player_lt = 90.0

            t_now = float(core.sg("SessionTime", 0.0) or 0.0)

            try:
                _dm = core.driver_map() or {}
            except Exception:
                _dm = {}

            est_arr = core.sg("CarIdxEstTime", []) or []  # 261001_CURSOR
            surf_arr = core.sg("CarIdxTrackSurface", []) or []  # 261001_CURSOR
            weekend = core.sg("WeekendInfo", {}) or {}  # 261001_CURSOR
            length_m = None  # 261001_CURSOR
            try:  # 261001_CURSOR
                parts = str(weekend.get("TrackLength", "")).lower().split()  # 261001_CURSOR
                length_m = float(parts[0])  # 261001_CURSOR
                if len(parts) > 1 and parts[1].startswith("km"):  # 261001_CURSOR
                    length_m *= 1000.0  # 261001_CURSOR
                elif len(parts) > 1 and parts[1].startswith("mi"):  # 261001_CURSOR
                    length_m *= 1609.344  # 261001_CURSOR
            except (ValueError, IndexError, AttributeError):  # 261001_CURSOR
                length_m = None  # 261001_CURSOR
            self._timing.update(  # 261001_CURSOR
                pi, _dm, dp_arr, est_arr, surf_arr,  # 261001_CURSOR
                session_key=(getattr(core, "_SESSION_SIG", [None])[0], getattr(core, "_RESET_EPOCH", [0])[0]),  # 261001_CURSOR
                session_time=t_now,  # 261001_CURSOR
                track_length_m=length_m,  # 261001_CURSOR
                fallback_lap_time=player_lt,  # 261001_CURSOR
            )  # 261001_CURSOR

            seen = set()
            for ci in range(len(dp_arr)):
                if ci == pi:
                    continue
                try:
                    odp = float(dp_arr[ci])
                except Exception:
                    continue
                if odp < 0:
                    continue
                if ci < len(op_arr) and bool(op_arr[ci]):
                    continue

                drv = _dm.get(ci) or {}
                try:
                    if core._is_safety_car(drv):
                        continue
                except Exception:
                    pass

                # gap = self._gap_to(pdp, odp, player_lt)
                gap, _timing_debug = self._timing.gap(ci)  # 261001_CURSOR
                if gap is None:
                    continue
                if gap <= 0 or gap > self.gap_max:
                    continue

                seen.add(ci)
                dq = self._gap_hist.setdefault(ci, deque())
                dq.append((t_now, gap))
                while dq and (t_now - dq[0][0]) > self.history_s:
                    dq.popleft()

            for ci in list(self._gap_hist.keys()):
                if ci not in seen:
                    del self._gap_hist[ci]
        except Exception as ex:
            core._log(f"Alert sample error: {ex!r}")

    def _is_qualify_session(self):
        try:
            si = core.sg("SessionInfo", None) or {}
            sn = int(core.sg("SessionNum", 0) or 0)
            sessions = si.get("Sessions") or []
            if 0 <= sn < len(sessions):
                st = str(sessions[sn].get("SessionType", "") or "").lower()
                if "qualify" in st:
                    return True
        except Exception:
            pass
        return False

    def _compute_alert(self):
        """Returns dict {active,count,min_gap,worst_rate,cars} or None."""
        if self._is_qualify_session():
            return None

        active = []
        for ci, dq in self._gap_hist.items():
            if len(dq) < 2:
                continue
            t0, g0 = dq[0]
            t1, g1 = dq[-1]
            dt = t1 - t0
            if dt <= 0.2:
                continue
            rate = (g1 - g0) / dt
            if rate <= -self.rate_threshold and 0 < g1 <= self.gap_max:
                active.append((ci, g1, rate))

        if not active:
            return None

        active.sort(key=lambda x: x[1])
        return {
            "active": True,
            "count": len(active),
            "min_gap": active[0][1],
            "worst_rate": active[0][2],
            "cars": [a[0] for a in active],
        }

    def _flag_states(self):
        try:
            sf = int(core.sg("SessionFlags", 0) or 0)
        except Exception:
            sf = 0
        return {
            "yellow": bool(sf & FLAG_YELLOW or sf & FLAG_YELLOW_WAVING or sf & FLAG_CAUTION or sf & FLAG_CAUTION_WAVING),
            "dirty": bool(sf & FLAG_DEBRIS),
            "blue": bool(sf & FLAG_BLUE),
        }

    def _resolve_mode(self, alert_res):
        candidates = []
        if alert_res:
            candidates.append((self.priority_alert, 0, "alert"))

        flags = self._flag_states()
        if flags["yellow"]:
            candidates.append((self.priority_yellow, 1, "yellow"))
        if flags["dirty"]:
            candidates.append((self.priority_dirty, 2, "dirty"))
        if flags["blue"]:
            candidates.append((self.priority_blue, 3, "blue"))

        if not candidates:
            return None, None, flags

        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2], candidates[0][0], flags

    # -- paint -------------------------------------------------------------

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            from PyQt6.QtGui import QPainter as _QP

            try:
                p.setCompositionMode(_QP.CompositionMode.CompositionMode_Source)
                p.fillRect(self.rect(), QColor(0, 0, 0, 0))
                p.setCompositionMode(_QP.CompositionMode.CompositionMode_SourceOver)
            except Exception:
                pass

            res = self._compute_alert()
            mode, priority, flags = self._resolve_mode(res)
            now_t = _time.time()
            if mode != self._active_mode:
                self._active_mode = mode
                self._active_since = now_t
            if not mode:
                if self.show_border or self._force_outline:
                    from PyQt6.QtGui import QPen as _QPen
                    pen_color = QColor(255, 200, 0) if self._force_outline else QColor(120, 120, 120)
                    pen = _QPen(pen_color, 2)
                    p.setPen(pen)
                    p.drawRect(1, 1, self.width() - 2, self.height() - 2)
                    if self._force_outline:
                        from PyQt6.QtGui import QFont as _QFont
                        f = _QFont(self.font_bold)
                        f.setPointSize(max(8, int(self.height() * 0.25)))
                        p.setFont(f)
                        p.drawText(
                            self.rect(),
                            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                            "ALERT (drag me)",
                        )

                self._last_payload = {
                    "active": False,
                    "mode": None,
                    "flags": flags,
                }
                core.update_state_and_debug_dump(extra={"alert": self._last_payload})
                return

            if (now_t - self._active_since) < self.activation_delay_s:
                self._last_payload = {
                    "active": False,
                    "mode": mode,
                    "pending": True,
                    "flags": flags,
                }
                core.update_state_and_debug_dump(extra={"alert": self._last_payload})
                return

            phase = (now_t * self.flash_hz) % 1.0
            on = phase < 0.5

            if mode == "alert":
                bg = QColor(220, 30, 30) if on else QColor(120, 0, 0)
                fg = QColor(255, 255, 255)
            elif mode == "yellow":
                bg = QColor(255, 225, 35) if on else QColor(170, 145, 0)
                fg = QColor(0, 0, 0)
            elif mode == "dirty":
                bg = QColor(255, 145, 0) if on else QColor(150, 82, 0)
                fg = QColor(0, 0, 0)
            else:
                bg = QColor(40, 130, 255) if on else QColor(0, 72, 170)
                fg = QColor(255, 255, 255)

            p.fillRect(self.rect(), bg)
            p.setPen(fg)

            w = self.width()
            h = self.height()

            font = QFont(self.font_bold)
            font.setBold(True)
            font.setPointSize(max(14, int(h * 0.45)))
            p.setFont(font)
            p.drawText(
                QRect(0, 0, w, h),
                Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter,
                "ALERT",
            )

            payload = {
                "active": True,
                "mode": mode,
                "priority": int(priority),
                "flags": flags,
            }
            if res:
                payload.update({
                    "count": res["count"],
                    "min_gap": round(res["min_gap"], 3),
                    "worst_rate": round(res["worst_rate"], 3),
                    "cars": list(res["cars"]),
                })
            self._last_payload = payload
            core.update_state_and_debug_dump(extra={"alert": self._last_payload})

        except Exception as ex:
            core._log(f"Alert paint error: {ex!r}")
            core._log(traceback.format_exc())
