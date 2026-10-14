# relative
from PyQt6.QtGui import QPainter, QColor, QFontMetrics
from PyQt6.QtCore import Qt, QRect
import traceback

import core
from blacklist import normalize_user_id
from base import TableWin
from country_codes import country_code
from relative_timing import RelativeTiming, track_position, wrap_fraction
from driver_format import fmt_avg_delta as _fmt_avg_delta, inc_for_car as _inc_for_car  # 261001_CURSOR


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



def _fmt_interval(sec):
    """Format a signed interval in seconds. Positive = ahead (green), negative = behind (red)."""
    if sec is None:
        return "", core.CLR_WHITE
    try:
        sec = float(sec)
    except Exception:
        return "", core.CLR_WHITE
    if abs(sec) < 1e-6:
        return "0", core.CLR_WHITE
    abs_sec = abs(sec)
    txt = str(int(round(abs_sec))) if abs_sec >= 100 else f"{abs_sec:.1f}"
    return txt, (core.CLR_GREEN if sec > 0 else core.CLR_RED)


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


class Relative(TableWin):
    def __init__(self):
        s = core.cfg.get("relative_settings") or {}
        cols = s.get("columns") or []
        super().__init__("relative", cols)
        self._enable_marked_number_column_once(s)
        self.ahead = int(s.get("rows_ahead", 3))
        self.behind = int(s.get("rows_behind", 3))
        self.avg_laps = int(s.get("avg_laps", 5))
        self._last_rows = []
        self._timing = RelativeTiming()
        self._last_sig = None
        self._last_reset_epoch = 0
        # Stores last computed row layout for hit-testing on click. List of
        # (rect_y_top, rect_y_bot, row_dict). Repopulated each paint.
        self._row_hit_zones = []

    def _enable_marked_number_column_once(self, settings):
        """Expose car numbers for the new marker without overriding later edits."""
        if settings.get("marked_num_column_ready"):
            return
        number_col = next((col for col in self.columns if col.get("id") == "num"), None)
        if number_col is None:
            return
        number_col["enabled"] = True
        number_col["width"] = max(
            int(number_col.get("width", 25)),
            QFontMetrics(self.font_normal).horizontalAdvance("999!") + 6,
        )
        needed_width = sum(int(col.get("width", 40)) for col in self.columns
                           if col.get("enabled", True)) + 2 * core.PAD_X
        if self.width() < needed_width:
            right = self.x() + self.width()
            new_x = max(0, right - needed_width)
            self.setGeometry(new_x, self.y(), needed_width, self.height())
            self._max_w = needed_width
            core.cfg.setdefault("windows", {}).setdefault("relative", {}).update(
                x=new_x, width=needed_width)
        settings["marked_num_column_ready"] = True
        core.save_cfg()

    def update_data(self):
        # if core.connect():
        #     try:
        #         core.ir.freeze_var_buffer_latest()
        #     except Exception:
        #         pass
        core.begin_frame()  # 261001_CURSOR
        self.update()

    # ---- click-to-report-bug ----
    def mousePressEvent(self, ev):
        """Left-click on a row's 'report' cell flags that row's data into
        a debug log so we can investigate ordering / INT issues offline.
        Falls through to BaseWin's drag handler for clicks elsewhere."""
        try:
            from PyQt6.QtCore import Qt as _Qt
            if ev.button() == _Qt.MouseButton.LeftButton:
                pos = ev.position().toPoint()
                # Find which row was clicked
                clicked_row = None
                for top, bot, row in self._row_hit_zones:
                    if top <= pos.y() <= bot:
                        clicked_row = row
                        break
                # Find the report-cell x-range (only flag if click is in it)
                if clicked_row is not None and not clicked_row.get("_blank"):
                    # Skip blank padding rows (no real car to flag)
                    active_cols = [c for c in self.columns if c.get("enabled", True)]
                    x = core.PAD_X
                    in_report = False
                    for col in active_cols:
                        cw = int(col.get("width", 40))
                        if col.get("id") == "report":
                            if x <= pos.x() <= x + cw:
                                in_report = True
                                break
                        x += cw
                    if in_report:
                        self._log_report(clicked_row)
                        # Visual ack: highlight the row briefly via repaint;
                        # the persistent flag isn't reflected in display
                        # state — just in the debug log.
                        self.update()
                        return
        except Exception as ex:
            core._log(f"Relative click error: {ex!r}")
        # Not a report click → fall through to drag-to-move
        super().mousePressEvent(ev)

    def _log_report(self, row):
        """Write a structured "user-flagged this relative row as wrong"
        record to a per-session JSONL bug-report file so it can be
        cross-referenced with the data_*.json capture afterwards.

        Captures everything we'd need to investigate the row offline:
        the player's track position, the flagged car's full row dict
        (which includes _int_sec / _dd_frac / _method / _lc_diff / etc.
        from the relative INT computation), session signature, and a
        mini snapshot of the surrounding telemetry."""
        import json as _json
        import time as _time
        try:
            t_now = _time.strftime("%Y-%m-%d %H:%M:%S")
            sess_t = float(core.sg("SessionTime", 0.0) or 0.0)
            pi = core.player_idx()
            dp_arr  = core.sg("CarIdxLapDistPct", []) or []
            lc_arr  = core.sg("CarIdxLapCompleted", []) or []
            est_arr = core.sg("CarIdxEstTime", []) or []
            cl_arr  = core.sg("CarIdxClass", []) or []
            op_arr  = core.sg("CarIdxOnPitRoad", []) or []
            sig = core._SESSION_SIG[0]
            target_idx = row.get("_idx")
            payload = {
                "timestamp": t_now,
                "session_time": sess_t,
                "session_sig": list(sig) if sig else None,
                "player_idx": pi,
                "player_dp":  float(dp_arr[pi]) if isinstance(pi, int) and pi < len(dp_arr) else None,
                "player_lc":  int(lc_arr[pi])   if isinstance(pi, int) and pi < len(lc_arr) else None,
                "flagged_row": {k: v for k, v in row.items()
                                if not isinstance(v, (bytes,))
                                and not str(type(v).__name__).startswith("Q")},
                "target_state": (
                    {
                        "idx":       target_idx,
                        "dp":        float(dp_arr[target_idx])  if isinstance(target_idx, int) and target_idx < len(dp_arr)  else None,
                        "lc":        int(lc_arr[target_idx])    if isinstance(target_idx, int) and target_idx < len(lc_arr)  else None,
                        "est_time":  float(est_arr[target_idx]) if isinstance(target_idx, int) and target_idx < len(est_arr) else None,
                        "class_id":  int(cl_arr[target_idx])    if isinstance(target_idx, int) and target_idx < len(cl_arr)  else None,
                        "on_pit":    bool(op_arr[target_idx])   if isinstance(target_idx, int) and target_idx < len(op_arr)  else None,
                    } if target_idx is not None else None
                ),
                "all_visible_rows": [
                    {k: v for k, v in r.items()
                     if not isinstance(v, (bytes,))
                     and not str(type(v).__name__).startswith("Q")}
                    for r in self._last_rows
                ],
            }
            import os as _os
            ts = _time.strftime("%Y%m%d")
            path = _os.path.join(
                core.DEBUG_ARCHIVE_DIR, f"relative_reports_{ts}.jsonl"
            )
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(_json.dumps(payload, default=str) + "\n")
            core._log(f"Relative bug-report flagged: car_idx={target_idx} "
                      f"@ t={sess_t:.1f}s → {path}")
        except Exception as ex:
            core._log(f"Failed to write relative bug-report: {ex!r}")

    def paintEvent(self, e):

        try:
            p = QPainter(self)
            if not core.ir.is_connected:
                self._timing.reset()
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_normal)
                p.setPen(core.CLR_WHITE)
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y, self.width() - 2 * core.PAD_X, self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "RELATIVE: DISCONNECTED",
                )
                return

            # Reset-grace placeholder: for ~3s after a session-change is
            # detected, render an empty table instead of stale data. This
            # gives pyirsdk's YAML cache time to repopulate with the new
            # session's drivers/positions; otherwise we'd render the previous
            # session's rows for a few frames after the reset.
            if core.is_in_reset_grace():
                self._timing.reset()
                p.fillRect(self.rect(), QColor(0, 0, 0))
                p.setFont(self.font_bold)
                p.setPen(QColor(255, 200, 0))
                p.drawText(
                    QRect(core.PAD_X, core.PAD_Y,
                          self.width() - 2 * core.PAD_X,
                          self.height() - 2 * core.PAD_Y),
                    Qt.AlignmentFlag.AlignCenter,
                    "RELATIVE: NEW SESSION…",
                )
                self._last_rows = []
                # Force-tick the reset bookkeeping while we're here so the
                # very first paint after grace expires sees a fresh state.
                try:
                    self._last_sig = core._SESSION_SIG[0]
                    self._last_reset_epoch = core._RESET_EPOCH[0]
                except Exception:
                    pass
                return

            core.init_start_positions()

            if core.session_time() < 5:
                core.start_class_pos.clear()
                core.init_start_positions()

            # --- Session-change reset: wipe cached rows so the table doesn't
            # flash stale cars/intervals from the previous session. Watches
            # both the signature tuple AND the _RESET_EPOCH counter (which
            # bumps on tick-backward jumps even when the YAML-derived sig
            # hasn't caught up yet). ---
            try:
                _cur_sig = core._SESSION_SIG[0]
                _cur_epoch = core._RESET_EPOCH[0]
                if _cur_sig != self._last_sig or _cur_epoch != self._last_reset_epoch:
                    self._last_sig = _cur_sig
                    self._last_reset_epoch = _cur_epoch
                    self._last_rows = []
            except Exception:
                pass

            dm = core.driver_map()
            pi = core.player_idx()

            if not dm or pi not in dm:
                self.draw(p, [])
                return

            core.update_state_and_debug_dump()

            # Reset per-tick debug map for INT calcs. Populated below when we
            # compute each candidate's interval, then attached to its row.
            self._row_debug = {}

            class_pos = core.sg("CarIdxClassPosition", [])
            tire = core.sg("CarIdxTireCompound", [])

            # keep runtime state fresh (LPIT relies on this)

            lapc = core.sg("CarIdxLapCompleted", []) or []
            dist = core.sg("CarIdxLapDistPct", []) or []
            track_surf = core.sg("CarIdxTrackSurface", []) or []
            est_arr = core.sg("CarIdxEstTime", []) or []
            if not isinstance(pi, int) or pi < 0 or pi >= len(dist):
                self.draw(p, [])
                return
            player_dist_pct = track_position(dist[pi])
            if player_dist_pct is None or (pi < len(track_surf) and track_surf[pi] < 0):
                self.draw(p, [])
                return

            player_class_id = dm[pi].get("CarClassID", -1)
            weekend = core.sg("WeekendInfo", {}) or {}
            length_m = None
            try:
                parts = str(weekend.get("TrackLength", "")).lower().split()
                length_m = float(parts[0])
                if len(parts) > 1 and parts[1].startswith("km"):
                    length_m *= 1000.0
                elif len(parts) > 1 and parts[1].startswith("mi"):
                    length_m *= 1609.344
            except (ValueError, IndexError):
                pass

            # One clock for every row, including different models within the
            # player's class. Completed laps never change this timing method.
            self._timing.update(
                pi, dm, dist, est_arr, track_surf,
                session_key=(core._SESSION_SIG[0], core._RESET_EPOCH[0],
                             weekend.get("TrackID"), weekend.get("TrackConfigName")),
                session_time=core.sg("SessionTime", None),
                track_length_m=length_m,
                fallback_lap_time=core.avg_sec_filtered(pi, 3, 8.0),
            )
            candidates = []
            gap_map = {pi: 0.0}
            for idx, drv in dm.items():
                if idx == pi or idx < 0 or core._is_safety_car(drv) or idx >= len(dist):
                    continue
                if idx < len(track_surf) and track_surf[idx] < 0:
                    continue
                other_dist_pct = track_position(dist[idx])
                if other_dist_pct is None:
                    continue
                dd_frac = wrap_fraction(other_dist_pct - player_dist_pct)
                int_sec, timing_debug = self._timing.gap(idx)
                gap_map[idx] = int_sec
                candidates.append((dd_frac, idx))
                try:
                    lc_diff = max(0, int(lapc[idx])) - max(0, int(lapc[pi]))
                except (ValueError, TypeError, IndexError):
                    lc_diff = 0
                other_cid = drv.get("CarClassID", -1)
                self._row_debug[idx] = {
                    "dd_frac": dd_frac, "lc_diff": lc_diff,
                    "int_sec": int_sec, "sign": 1 if dd_frac >= 0 else -1,
                    "same_class": other_cid == player_class_id,
                    "method": timing_debug["source"], "other_cid": other_cid,
                    "ahead_idx": idx if dd_frac > 0 else pi,
                    "behind_idx": pi if dd_frac > 0 else idx,
                    "profile_debug": timing_debug,
                }

            # ---- Window selection: irdashies' algorithm verbatim ----
            # Port of useDriverRelatives.tsx:
            #     processed.sort((a, b) => b.relativePct - a.relativePct);
            #     const playerIdx = processed.findIndex((d) => d.carIdx === focusCarIdx);
            #     const start = Math.max(0, playerIdx - buffer);
            #     const end   = Math.min(processed.length, playerIdx + 1 + buffer);
            #     const visibleDrivers = processed.slice(start, end);
            #
            # Build ONE list of every valid car (player included), sort
            # DESC by dd_frac, find the player's position, slice ±buffer
            # around them. Mathematically equivalent to the older two-bucket
            # approach when buffers are equal, but more robust for edge
            # cases — small fields, all cars on one side of the player,
            # asymmetric buffer-ahead vs buffer-behind, ties.
            #
            # Stable tiebreaker on car_idx ensures cars with EXACTLY the
            # same dd_frac (e.g. spawning on the grid before any movement
            # has been recorded) keep a deterministic order rather than
            # flickering frame-to-frame as iRacing rebuilds the dict.
            sortable = list(candidates)             # [(dd_frac, idx), ...]
            sortable.append((0.0, pi))              # include player at dd=0
            # Sort DESC by dd_frac, ASC by idx as tiebreaker
            sortable.sort(key=lambda t: (-t[0], t[1]))

            # Find the player's position in the sorted list
            try:
                player_pos = next(i for i, (_, idx) in enumerate(sortable) if idx == pi)
            except StopIteration:
                player_pos = 0

            start = max(0, player_pos - self.ahead)
            end   = min(len(sortable), player_pos + 1 + self.behind)
            window = [idx for _, idx in sortable[start:end]]

            # ---- Fixed-height window (ahead + 1 + behind rows always) ----
            # Pad the window so the table always has the same number of rows
            # — `self.ahead` cars above the player, the player, then
            # `self.behind` cars below — even when there aren't enough real
            # opponents around. We use the sentinel value None for missing
            # slots; row-build below renders them as a blank "ghost" row of
            # the right height so the widget's geometry stays stable.
            n_target_above = self.ahead
            n_target_below = self.behind

            # How many real cars do we have above / below the player?
            try:
                player_in_window = window.index(pi)
            except ValueError:
                player_in_window = 0
            n_above = player_in_window
            n_below = max(0, len(window) - player_in_window - 1)

            # Pad above (prepend Nones) and below (append Nones)
            pad_above = [None] * max(0, n_target_above - n_above)
            pad_below = [None] * max(0, n_target_below - n_below)
            window = pad_above + window + pad_below

            _avg_n = self.avg_laps
            player_avg_sec = core.avg_sec_filtered(pi, _avg_n, 5.0)

            rows = []
            marked_ids = core.blacklist_ids()
            for car_idx in window:
                # Padding slot — render as a blank "ghost" row so the table's
                # height is constant (ahead + 1 + behind rows). User asked
                # for fixed 7-row layout so the window doesn't shrink/grow
                # when fewer real cars are around the player.
                if car_idx is None:
                    rows.append({
                        # Empty cell values for every column we render
                        "pos": "", "num": "", "num_color": core.CLR_GRID,
                        "brand": "", "ir": "", "ir_color": core.CLR_GRID,
                        "int": "", "int_color": core.CLR_GRID,
                        "flag": "", "p": "", "p_color": core.CLR_GRID,
                        "best": "", "avg": "", "avg_color": core.CLR_GRID,
                        "last": "", "inc": "", "pen": "",
                        "pen_color": core.CLR_GRID, "tire": "",
                        "lppit": "", "pittime": "",
                        "report": "", "report_color": core.CLR_GRID,
                        "laps_diff": 0, "is_player": False,
                        "_idx": None, "_int_sec": None, "_dd_frac": None,
                        "_lc_diff": None, "_sign": None, "_method": None,
                        "_same_class": None, "_other_cid": None,
                        "_blank": True,
                    })
                    continue
                drv = dm.get(car_idx, {})
                if core._is_safety_car(drv):
                    continue

                cp = class_pos[car_idx] if class_pos and len(class_pos) > car_idx else 0

                if car_idx == pi:
                    int_txt, int_col = "0", core.CLR_WHITE
                else:
                    int_txt, int_col = _fmt_interval(gap_map.get(car_idx))

                p_txt, p_col = core.pos_gain(car_idx, cp)
                best, last = core.best_last(car_idx)

                try:
                    cid = int(drv.get("CarClassID", -1))
                except Exception:
                    cid = -1

                inc_txt = _inc_for_car(car_idx, drv, pi)

                # ---- LAPS DIFF (for number decoration) ----
                try:
                    laps_diff = int(lapc[car_idx]) - int(lapc[pi]) if car_idx != pi else 0
                except Exception:
                    laps_diff = 0

                car_avg_sec = core.avg_sec_filtered(car_idx, _avg_n, 5.0)
                avg_txt, avg_col = _fmt_avg_delta(player_avg_sec, car_avg_sec, is_player=(car_idx == pi))

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

                pen_col = core.CLR_RED if pen_txt else core.CLR_GRID

                # ---- SDr / iRating (robust) ----
                raw_ir = drv.get("IRating", None)
                if raw_ir is None:
                    ir_arr = core.sg("CarIdxIRating", None)
                    if isinstance(ir_arr, (list, tuple)) and len(ir_arr) > car_idx:
                        raw_ir = ir_arr[car_idx]

                try:
                    ir_txt = core.ir_short("", raw_ir) if raw_ir is not None else ""
                except Exception:
                    ir_txt = ""

                ir_col = core.sr_color_from_lic(drv)

                # ---- LPIT: laps since last pit stop ----
                # Three-layer source (see standings.py for full reasoning):
                #   1. core.pit_entry_time tracked this session → use in-memory pit-lap
                #   2. core.last_pit_lap_completed has the value → use it
                #   3. DB fallback (pit_last_lap) for cars that pitted before
                #      the widget started observing.
                lppit = ""
                try:
                    _lc_arr = core.sg("CarIdxLapCompleted", [])
                    if isinstance(_lc_arr, (list, tuple)) and len(_lc_arr) > car_idx:
                        _cur = int(_lc_arr[car_idx])
                        _pit = None
                        if (core.pit_entry_time.get(car_idx) is not None
                                or car_idx in core.last_pit_lap_completed):
                            _pit = int(core.last_pit_lap_completed.get(car_idx, _cur))
                        if _pit is None and drv:
                            _pit_db = core.pit_last_lap(car_idx, drv)
                            if _pit_db and _pit_db > 0:
                                _pit = int(_pit_db)
                        if _pit is not None and _pit >= 0:
                            lppit = str(max(0, _cur - _pit))
                except Exception:
                    pass

                # Raw-number debug fields so `_widgets.relative.rows` in the
                # capture files shows exactly what this widget computed, not
                # just the formatted display text. Prefixed with _ so any
                # future display code ignores them. car_idx is also stored
                # explicitly because `num` is a string and can collide.
                _dbg = getattr(self, "_row_debug", {}).get(car_idx, {}) if car_idx != pi else {}
                car_number = str(drv.get("CarNumber", ""))
                user_id = normalize_user_id(drv.get("UserID"))
                if car_number and user_id is not None and user_id in marked_ids:
                    car_number += "!"
                _row = {
                    "pos": str(cp) if cp else "",
                    "num": car_number,
                    "num_color": core.class_color(cid),
                    "brand": core.brand3(drv.get("CarScreenNameShort", "")),
                    "ir": ir_txt,
                    "ir_color": ir_col,
                    "int": int_txt,
                    "int_color": int_col,
                    "flag": country_code(drv.get("FlairName", "")),
                    "p": p_txt,
                    "p_color": p_col,
                    "best": best,
                    "avg": avg_txt,
                    "avg_color": avg_col,
                    "last": last,
                    "inc": inc_txt,
                    "pen": pen_txt,
                    "pen_color": pen_col,
                    "tire": core.tire_letter(tire[car_idx]) if tire and len(tire) > car_idx else "",
                    "lppit": lppit,
                    "pittime": core.pit_time(car_idx),
                    "laps_diff": laps_diff,
                    "is_player": (car_idx == pi),
                    # "report" cell — clickable bug-report marker (item 6).
                    # Shown as "!" so the user has a visible target for their
                    # click. Click handler in mousePressEvent dumps the row's
                    # state to relative_reports_<DATE>.jsonl for offline
                    # analysis. Empty for the player's own row.
                    "report": "" if car_idx == pi else "!",
                    "report_color": QColor(255, 200, 80),
                    "_idx": car_idx,
                    "_int_sec": _dbg.get("int_sec"),
                    "_dd_frac": _dbg.get("dd_frac"),
                    "_lc_diff": _dbg.get("lc_diff"),
                    "_sign": _dbg.get("sign"),
                    "_method": _dbg.get("method"),
                    "_same_class": _dbg.get("same_class"),
                    "_other_cid": _dbg.get("other_cid"),
                    "_ahead_idx": _dbg.get("ahead_idx"),
                    "_behind_idx": _dbg.get("behind_idx"),
                    "_behind_lt": _dbg.get("behind_lt"),
                    "_profile": _dbg.get("profile_debug"),
                }
                rows.append(_row)

            self._last_rows = rows
            core.update_state_and_debug_dump(extra={"relative": {"rows": rows}})
            self.draw(p, rows)

            # Populate row hit-zones for click-to-report. Y positions match
            # base.TableWin.draw() exactly: header at top, then content rows
            # of height core.ROW_H starting at PAD_Y + ROW_H.
            self._row_hit_zones = []
            y0 = core.PAD_Y + core.ROW_H
            for r in rows:
                self._row_hit_zones.append((y0, y0 + core.ROW_H, r))
                y0 += core.ROW_H

        except Exception as ex:
            core._log(f"Relative paint error: {ex!r}")
            core._log(traceback.format_exc())


# if correct reply yes, else return solutions that are mandatory to work
