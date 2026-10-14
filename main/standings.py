# standings
from PyQt6.QtGui import QPainter, QColor, QFont, QFontMetrics
from PyQt6.QtCore import Qt, QRect
from collections import defaultdict
import traceback

import core
from base import TableWin
from last_lap_ranking import format_lap_millis, format_top_lap_entry, top_last_laps
from driver_format import fmt_avg_delta as _fmt_avg_delta, inc_for_car as _inc_for_car  # 261001_CURSOR
from relative_timing import RelativeTiming  # 261001_CURSOR
from class_names import class_labels


# def _inc_for_car(car_idx: int, drv: dict, pi: int):
#     # Hide incidents while player/session isn't fully live yet (e.g. transition
#     # between Qualify -> Race with lap=-1), otherwise stale/heuristic values can flash.
#     try:
#         _lc_arr = core.sg("CarIdxLapCompleted", []) or []
#         _surf_arr = core.sg("CarIdxTrackSurface", []) or []
#         _pi_lc = int(_lc_arr[pi]) if pi < len(_lc_arr) else -1
#         _pi_surf = int(_surf_arr[pi]) if pi < len(_surf_arr) else -1
#         if _pi_lc < 0 or _pi_surf < 0:
#             return ""
#     except Exception:
#         return ""
#
#     # Accumulation is handled in core.update_state_and_debug_dump() every frame.
#     # We just read the cached total and optionally add player-specific sources.
#     total = core._inc_cache.get(car_idx, 0)
#     if car_idx == pi:
#         for _tvar in ("PlayerCarTeamIncidentCount", "PlayerCarMyIncidentCount", "PlayerCarDriverIncidentCount"):
#             try:
#                 _v = int(float(core.sg(_tvar, 0) or 0))
#                 if _v > total:
#                     total = _v
#             except Exception:
#                 pass
#     return str(total) if total > 0 else ""


# def _fmt_avg_delta(player_avg, car_avg, is_player=False):
#     if is_player:
#         return "0", core.CLR_WHITE
#     try:
#         pa = float(player_avg)
#         ca = float(car_avg)
#     except Exception:
#         return "", core.CLR_WHITE
#     d = pa - ca
#     if abs(d) < 0.05:
#         return "0", core.CLR_WHITE
#     return f"{d:.1f}", (core.CLR_GREEN if d < 0 else core.CLR_RED)


class Standings(TableWin):
    def __init__(self):
        s = core.cfg.get("standings_settings") or {}
        cols = s.get("columns") or []
        super().__init__("standings", cols)
        # Standings uses per-class header blocks (class row + column row),
        # so the global top header would duplicate the first class header.
        self._show_top_header = False
        self.ahead = int(s.get("rows_ahead", 5))
        self.behind = int(s.get("rows_behind", 5))
        self.top = int(s.get("top_per_class", 3))
        self.multiclass_headers = bool(s.get("multiclass_headers", True))
        self.show_top_last_laps = bool(s.get("show_top_last_laps", True))
        self.avg_laps = int(s.get("avg_laps", 5))
        self._last_rows = []
        self._last_sig = None
        self._last_reset_epoch = 0
        self._timing = RelativeTiming()  # 261001_CURSOR

    def _fit_top_lap_strip(self, rows):
        labels = [format_top_lap_entry(lap)
                  for row in rows for lap in row.get("_top_laps", [])]
        if not labels:
            return
        font = QFont(self.font_normal)
        font.setPointSize(max(8, font.pointSize() - 2))
        max_text_width = max(QFontMetrics(font).horizontalAdvance(label) for label in labels)
        wanted_width = 3 * (max_text_width + 8) + 2 * core.PAD_X
        if self.width() >= wanted_width:
            return
        right = self.x() + self.width()
        new_x = max(0, right - wanted_width)
        self.setGeometry(new_x, self.y(), wanted_width, self.height())
        self._max_w = wanted_width
        window_cfg = core.cfg.setdefault("windows", {}).setdefault("standings", {})
        window_cfg.update(x=new_x, width=wanted_width)
        core.save_cfg()

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    def _refresh_timing(self, pi, drivers):  # 261001_CURSOR
        dist = core.sg("CarIdxLapDistPct", []) or []  # 261001_CURSOR
        est_arr = core.sg("CarIdxEstTime", []) or []  # 261001_CURSOR
        track_surf = core.sg("CarIdxTrackSurface", []) or []  # 261001_CURSOR
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
        track_id = weekend.get("TrackID") if isinstance(weekend, dict) else None  # 261001_CURSOR
        self._timing.update(  # 261001_CURSOR
            pi, drivers, dist, est_arr, track_surf,  # 261001_CURSOR
            session_key=(core._SESSION_SIG[0], core._RESET_EPOCH[0], track_id),  # 261001_CURSOR
            session_time=core.sg("SessionTime", None),  # 261001_CURSOR
            track_length_m=length_m,  # 261001_CURSOR
            fallback_lap_time=core.avg_sec_filtered(pi, 3, 8.0),  # 261001_CURSOR
        )  # 261001_CURSOR

    def _clock_behind(self, reference_idx, car_idx, lap_arr):  # 261001_CURSOR
        if reference_idx is None or car_idx is None:  # 261001_CURSOR
            return None  # 261001_CURSOR
        sec, _debug = self._timing.gap_between(reference_idx, car_idx)  # 261001_CURSOR
        if sec is None:  # 261001_CURSOR
            return None  # 261001_CURSOR
        behind = -float(sec)  # 261001_CURSOR
        lap_time = self._timing._lap or self._timing._fallback_lap  # 261001_CURSOR
        if lap_time and isinstance(lap_arr, (list, tuple)):  # 261001_CURSOR
            try:  # 261001_CURSOR
                if 0 <= reference_idx < len(lap_arr) and 0 <= car_idx < len(lap_arr):  # 261001_CURSOR
                    behind += (int(lap_arr[reference_idx]) - int(lap_arr[car_idx])) * float(lap_time)  # 261001_CURSOR
            except (TypeError, ValueError):  # 261001_CURSOR
                pass  # 261001_CURSOR
        return behind  # 261001_CURSOR

    def paintEvent(self, e):
        try:
            p = QPainter(self)
            if not core.ir.is_connected:
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_normal)
                p.setPen(core.CLR_WHITE)
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y, self.width() - 2 * core.PAD_X, self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "STANDINGS: DISCONNECTED",
                )
                return

            # Reset-grace placeholder (see relative.py for full reasoning).
            if core.is_in_reset_grace():
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_bold)
                p.setPen(QColor(255, 200, 0))
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y,
                          self.width() - 2 * core.PAD_X,
                          self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "STANDINGS: NEW SESSION…",
                )
                self._last_rows = []
                try:
                    self._last_sig = core._SESSION_SIG[0]
                    self._last_reset_epoch = core._RESET_EPOCH[0]
                except Exception:
                    pass
                return

            dm = core.driver_map()
            core.init_start_positions()
            pi = core.player_idx()

            core.update_state_and_debug_dump()

            # reset on session change — wipe last displayed rows so the table
            # doesn't flash stale data from the previous session while the new
            # one is being populated. Watches both signature AND _RESET_EPOCH
            # (bumped on tick-backward jumps too).
            sig = core._SESSION_SIG[0]
            epoch = core._RESET_EPOCH[0]
            if sig != self._last_sig or epoch != self._last_reset_epoch:
                self._last_sig = sig
                self._last_reset_epoch = epoch
                self._last_rows = []


            class_pos = core.sg("CarIdxClassPosition", [])
            tire = core.sg("CarIdxTireCompound", [])
            last_lap_times = core.sg("CarIdxLastLapTime", [])

            classes = defaultdict(list)  # cid -> [(class_pos, car_idx)]
            class_names = class_labels(dm.values())
            for idx, drv in dm.items():
                if core._is_safety_car(drv):
                    continue
                try:
                    cid = int(drv.get("CarClassID", -1))
                except Exception:
                    cid = -1
                if cid == -1:
                    continue
                try:
                    cp = int(class_pos[idx]) if class_pos and len(class_pos) > idx else 0
                except Exception:
                    cp = 0
                if cp <= 0:
                    continue
                classes[cid].append((cp, idx))

            for cid in list(classes.keys()):
                classes[cid].sort(key=lambda x: x[0])

            try:
                player_class = int(dm.get(pi, {}).get("CarClassID", -1))
                if player_class == -1:
                    player_class = None
            except Exception:
                player_class = None

            class_order = []
            if player_class is not None and player_class in classes:
                class_order.append(player_class)
            for cid in sorted(classes.keys()):
                if cid not in class_order:
                    class_order.append(cid)

            prev_in_class = {}
            for cid, arr in classes.items():
                for k, (cp, idx) in enumerate(arr):
                    prev_in_class[idx] = arr[k - 1][1] if k > 0 else None

            # ---- read F2Time once (cumulative gap-to-leader per car, updated every frame) ----
            _f2t = core.sg("CarIdxF2Time", [])
            try:  # 261001_CURSOR
                self._refresh_timing(pi, dm)  # 261001_CURSOR
            except Exception:  # 261001_CURSOR
                self._timing.reset()  # 261001_CURSOR
            _clock_laps = core.sg("CarIdxLapCompleted", []) or []  # 261001_CURSOR

            _avg_n = self.avg_laps
            player_avg_sec = core.avg_sec_filtered(pi, _avg_n, 5.0)
            lapc_s = core.sg("CarIdxLapCompleted", [])
            try:
                pi_laps = int(lapc_s[pi]) if lapc_s and len(lapc_s) > pi else 0
            except Exception:
                pi_laps = 0

            def class_label(cid: int) -> str:
                lbl = str(class_names.get(cid, "") or "").strip()
                if lbl:
                    return lbl
                if int(cid) >= 0:
                    return f"CLASS {int(cid)}"
                return "CLASS"

            rows = []

            for cid in class_order:
                arr = classes.get(cid, [])
                if not arr:
                    continue

                separator = {"_separator": True, "label": class_label(cid)}
                if self.show_top_last_laps:
                    class_drivers = {idx: dm[idx] for _cp, idx in arr}
                    class_positions = {idx: cp for cp, idx in arr}
                    fastest = top_last_laps(class_drivers, last_lap_times, tire)
                    separator["_top_laps"] = [
                        {
                            "pos": str(class_positions[lap["_idx"]]),
                            "num": str(dm[lap["_idx"]].get("CarNumber", "")),
                            "bestLap": format_lap_millis(lap["last_sec"]),
                            "tyre": core.tire_letter(lap["compound"]) or "—",
                            "_idx": lap["_idx"],
                        }
                        for lap in fastest
                    ]
                rows.append(separator)

                selected = []
                selected.extend(arr[: self.top])

                if cid == player_class:
                    ppos = 0
                    for j, (cp, idx) in enumerate(arr):
                        if idx == pi:
                            ppos = j
                            break
                    lo = max(0, ppos - self.ahead)
                    hi = min(len(arr), ppos + self.behind + 1)
                    selected.extend(arr[lo:hi])

                seen = set()
                sel = []
                for cp, idx in selected:
                    if idx in seen:
                        continue
                    seen.add(idx)
                    sel.append((cp, idx))
                sel.sort(key=lambda t: t[0])

                leader_idx = arr[0][1] if arr else None

                for cp, car_idx in sel:
                    drv = dm.get(car_idx, {})
                    best, last = core.best_last(car_idx)

                    car_avg_sec = core.avg_sec_filtered(car_idx, _avg_n, 5.0)
                    avg_txt, avg_col = _fmt_avg_delta(player_avg_sec, car_avg_sec, is_player=(car_idx == pi))

                    # ---- LAPS DIFF (for number decoration) ----
                    try:
                        _ld_arr = core.sg("CarIdxLapCompleted", [])
                        _pi_l = int(_ld_arr[pi]) if _ld_arr and len(_ld_arr) > pi else 0
                        laps_diff = int(_ld_arr[car_idx]) - _pi_l if _ld_arr and len(_ld_arr) > car_idx else 0
                    except Exception:
                        laps_diff = 0

                    ahead_idx = prev_in_class.get(car_idx)

                    # ---- GAP (to class leader) — CarIdxF2Time primary, EstTime fallback ----
                    gap_txt = ""
                    gap_col = core.CLR_WHITE
                    if car_idx != leader_idx:
                        try:
                            if (isinstance(_f2t, (list, tuple)) and
                                    len(_f2t) > max(car_idx, leader_idx)):
                                gv = float(_f2t[car_idx]) - float(_f2t[leader_idx])
                                gv_abs = abs(gv)
                                if gv_abs > 0.05:
                                    gap_txt = str(int(round(gv_abs))) if gv_abs >= 100 else f"{gv_abs:.1f}"
                                    gap_col = core.CLR_RED
                        except Exception:
                            pass
                        # if not gap_txt:
                        #     try:
                        #         _et_g = core.sg("CarIdxEstTime", [])
                        #         _lc_g = core.sg("CarIdxLapCompleted", [])
                        #         _dp_g = core.sg("CarIdxLapDistPct", [])
                        #         if (isinstance(_et_g, (list, tuple)) and isinstance(_lc_g, (list, tuple)) and
                        #                 isinstance(_dp_g, (list, tuple)) and
                        #                 len(_et_g) > max(car_idx, leader_idx) and
                        #                 len(_lc_g) > max(car_idx, leader_idx)):
                        #             tot_c = float(_lc_g[car_idx])    + max(0.0, float(_dp_g[car_idx]))
                        #             tot_l = float(_lc_g[leader_idx]) + max(0.0, float(_dp_g[leader_idx]))
                        #             n_laps = max(0, int(tot_l - tot_c))
                        #             lt = core._est_lap_time_for_player() or 0
                        #             gv = float(_et_g[car_idx]) - float(_et_g[leader_idx]) + n_laps * lt
                        #             gv_abs = abs(gv)
                        #             if gv_abs > 0.05:
                        #                 gap_txt = str(int(round(gv_abs))) if gv_abs >= 100 else f"{gv_abs:.1f}"
                        #                 gap_col = core.CLR_RED
                        #     except Exception:
                        #         pass
                        if not gap_txt:  # 261001_CURSOR
                            try:  # 261001_CURSOR
                                gv = self._clock_behind(leader_idx, car_idx, _clock_laps)  # 261001_CURSOR
                                if gv is not None and abs(gv) > 0.05:  # 261001_CURSOR
                                    gv_abs = abs(gv)  # 261001_CURSOR
                                    gap_txt = str(int(round(gv_abs))) if gv_abs >= 100 else f"{gv_abs:.1f}"  # 261001_CURSOR
                                    gap_col = core.CLR_RED  # 261001_CURSOR
                            except Exception:  # 261001_CURSOR
                                pass  # 261001_CURSOR

                    # ---- INT (to car directly ahead in class) — CarIdxF2Time primary, EstTime fallback ----
                    int_txt = ""
                    int_col = core.CLR_WHITE
                    if ahead_idx is not None:
                        try:
                            if (isinstance(_f2t, (list, tuple)) and
                                    len(_f2t) > max(car_idx, ahead_idx)):
                                iv = float(_f2t[car_idx]) - float(_f2t[ahead_idx])
                                iv_abs = abs(iv)
                                if iv_abs > 0.05:
                                    int_txt = str(int(round(iv_abs))) if iv_abs >= 100 else f"{iv_abs:.1f}"
                                    int_col = core.CLR_RED if iv > 0 else core.CLR_GREEN
                        except Exception:
                            pass
                        # if not int_txt:
                        #     try:
                        #         _et_i = core.sg("CarIdxEstTime", [])
                        #         _lc_i = core.sg("CarIdxLapCompleted", [])
                        #         _dp_i = core.sg("CarIdxLapDistPct", [])
                        #         if (isinstance(_et_i, (list, tuple)) and isinstance(_lc_i, (list, tuple)) and
                        #                 isinstance(_dp_i, (list, tuple)) and
                        #                 len(_et_i) > max(car_idx, ahead_idx) and
                        #                 len(_lc_i) > max(car_idx, ahead_idx)):
                        #             tot_c = float(_lc_i[car_idx])    + max(0.0, float(_dp_i[car_idx]))
                        #             tot_a = float(_lc_i[ahead_idx])  + max(0.0, float(_dp_i[ahead_idx]))
                        #             n_laps = max(0, int(tot_a - tot_c))
                        #             lt = core._est_lap_time_for_player() or 0
                        #             iv = float(_et_i[car_idx]) - float(_et_i[ahead_idx]) + n_laps * lt
                        #             iv_abs = abs(iv)
                        #             if iv_abs > 0.05:
                        #                 int_txt = str(int(round(iv_abs))) if iv_abs >= 100 else f"{iv_abs:.1f}"
                        #                 int_col = core.CLR_RED
                        #     except Exception:
                        #         pass
                        if not int_txt:  # 261001_CURSOR
                            try:  # 261001_CURSOR
                                iv = self._clock_behind(ahead_idx, car_idx, _clock_laps)  # 261001_CURSOR
                                if iv is not None and abs(iv) > 0.05:  # 261001_CURSOR
                                    iv_abs = abs(iv)  # 261001_CURSOR
                                    int_txt = str(int(round(iv_abs))) if iv_abs >= 100 else f"{iv_abs:.1f}"  # 261001_CURSOR
                                    int_col = core.CLR_RED if iv > 0 else core.CLR_GREEN  # 261001_CURSOR
                            except Exception:  # 261001_CURSOR
                                pass  # 261001_CURSOR


                    # ---- INCIDENTS (reuse same logic as RELATIVE) ----
                    inc_txt = _inc_for_car(car_idx, drv, pi)

                    # ---- PENALTIES ----
                    pen_txt = ""
                    try:
                        if car_idx == pi:
                            sf = int(core.sg("SessionFlags", 0) or 0)

                            # Correct irsdk_Flags masks
                            if sf & 0x00020000:      # irsdk_disqualify
                                pen_txt = "DQ"
                            elif sf & 0x00010000:    # irsdk_black
                                pen_txt = "PEN"
                            elif sf & 0x00100000:    # irsdk_repair (meatball)
                                pen_txt = "MEAT"
                            elif sf & 0x00080000:    # irsdk_furled
                                pen_txt = "CUT"

                        else:
                            sf_arr = core.sg("CarIdxSessionFlags", [])
                            if isinstance(sf_arr, (list, tuple)) and len(sf_arr) > car_idx:
                                sf = int(sf_arr[car_idx] or 0)
                                if sf & 0x00020000:
                                    pen_txt = "DQ"
                                elif sf & 0x00010000:
                                    pen_txt = "PEN"
                                elif sf & 0x00100000:
                                    pen_txt = "MEAT"
                                elif sf & 0x00080000:
                                    pen_txt = "CUT"

                    except Exception:
                        pass

                    # ---- LPIT: laps since last pit stop ----
                    # Three-layer source:
                    #   1. core.pit_entry_time observed THIS session — most
                    #      accurate (we tracked the actual op-transition).
                    #   2. core.last_pit_lap_completed (in-memory) — even
                    #      without entry-time, the lap number is enough.
                    #   3. core.pit_last_lap reading from DB — survives
                    #      session reset / late join, so cars that pitted
                    #      while the widget was idle still get a value.
                    # Without (3) the user reported empty LPIT for cars in
                    # multi-class races where they joined after the pit
                    # window had already started.
                    lppit_txt = ""
                    try:
                        _lc_arr = core.sg("CarIdxLapCompleted", [])
                        if isinstance(_lc_arr, (list, tuple)) and len(_lc_arr) > car_idx:
                            _cur = int(_lc_arr[car_idx])
                            _pit = None
                            # Layer 1+2: in-memory
                            if (core.pit_entry_time.get(car_idx) is not None
                                    or car_idx in core.last_pit_lap_completed):
                                _pit = int(core.last_pit_lap_completed.get(car_idx, _cur))
                            # Layer 3: DB fallback
                            if _pit is None and drv:
                                _pit_db = core.pit_last_lap(car_idx, drv)
                                if _pit_db and _pit_db > 0:
                                    _pit = int(_pit_db)
                            if _pit is not None and _pit >= 0:
                                lppit_txt = str(max(0, _cur - _pit))
                    except Exception:
                        pass

                    # ---- SDr / iRating (robust) ----
                    raw_ir = drv.get("IRating", None)
                    if raw_ir is None:
                        ir_arr = core.sg("CarIdxIRating", None)
                        if isinstance(ir_arr, (list, tuple)) and len(ir_arr) > car_idx:
                            raw_ir = ir_arr[car_idx]

                    try:
                        sdr_txt = core.ir_short("", raw_ir) if raw_ir is not None else ""
                    except Exception:
                        sdr_txt = ""

                    sdr_col = core.sr_color_from_lic(drv)

                    rows.append(
                        {
                            "pos": str(cp),
                            "num": str(drv.get("CarNumber", "")),
                            "num_color": core.class_color(cid),
                            "brand": core.brand3(drv.get("CarScreenNameShort", "")),
                            "ir": sdr_txt,
                            "ir_color": sdr_col,
                            "gap": gap_txt,
                            "gap_color": gap_col,
                            "int": int_txt,
                            "int_color": int_col,
                            "best": best,
                            "avg": avg_txt,
                            "avg_color": avg_col,
                            "last": last,
                            "inc": inc_txt,
                            "pen": pen_txt,
                            "pen_color": core.CLR_RED if pen_txt else core.CLR_GRID,
                            "tire": core.tire_letter(tire[car_idx]) if tire and len(tire) > car_idx else "",
                            "lppit": lppit_txt,
                            "pittime": core.pit_time(car_idx),
                            "laps_diff": laps_diff,
                            "is_player": (car_idx == pi),
                            "_idx": car_idx,
                        }
                    )

            self._last_rows = rows
            self._fit_top_lap_strip(rows)
            core.update_state_and_debug_dump(extra={"standings": {"rows": rows}})
            self.draw(p, rows)

        except Exception as ex:
            core._log(f"Standings paint error: {ex!r}")
            core._log(traceback.format_exc())


# if correct reply yes, else return solutions that are mandatory to work
