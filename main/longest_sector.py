"""Latest player sectors and class tyre rankings by latest complete lap."""

from collections import defaultdict
from PyQt6.QtGui import QPainter
import core
from sector_table import CompactSectorTable
from last_lap_ranking import format_lap_millis
from sector_timing import sector_columns
from class_names import class_labels


class LongestSector(CompactSectorTable):
    """Sectors display; the class/config key remains compatible with saved settings."""
    _timing_ids = ("sector", "sector_2", "sector_3")

    def __init__(self):
        settings = core.cfg.get("longest_sector_settings") or {}
        super().__init__("longest_sector", sector_columns(settings.get("columns")))
        self.setWindowTitle("Sectors")
        self._show_top_header = False
        self._uppercase_headers = False
        self._last_rows = self._waiting_rows("")
        self._last_payload = {"sectors": [], "rows": self._last_rows, "status": "WAITING"}
        self._fit_content(None, self._visible_row_count * self._text_height() + 2 * core.PAD_Y)

    def apply_settings(self, settings):
        self.columns = sector_columns(settings.get("columns"))
        self._fit_content(None, self._visible_row_count * self._text_height() + 2 * core.PAD_Y)
        self.update()

    @staticmethod
    def _blank_slot():
        return {"_empty": True, "pos": "", "num": "", "sector": "",
                "sector_2": "", "sector_3": "", "tire": ""}

    def _waiting_rows(self, heading):
        return [{"_separator": True, "label": heading}, self._blank_slot()] + [
            self._blank_slot() for _ in range(self._ranking_slots)]

    def _set_sector_headers(self, numbers):
        for col in self.columns:
            if col.get("id") in self._timing_ids:
                slot = self._timing_ids.index(col["id"])
                col["label"] = f"Setor {numbers[slot]}" if slot < len(numbers) else "Setor"

    def _car_row(self, idx, driver, tyre, car=None, rank=""):
        row = {"_idx": idx, "pos": str(rank), "num": str(driver.get("CarNumber", "")),
               "tire": tyre, "is_player": idx == core.player_idx()}
        row.update({key: "" for key in self._timing_ids})
        if car is not None:
            row.update(_seconds=car["seconds"])
            row.update({key: format_lap_millis(car["sectors"][slot])
                        if slot < len(car["sectors"]) else ""
                        for slot, key in enumerate(self._timing_ids)})
        return row

    def update_data(self):
        core.begin_frame()
        self.update()

    def _status(self, painter, text):
        self._set_sector_headers([])
        self._last_rows = self._waiting_rows("")
        self._last_payload = {"sectors": [], "rows": self._last_rows, "status": text}
        self.draw(painter, self._last_rows)

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            if not core.ir.is_connected:
                self._status(painter, "SECTORS: DISCONNECTED")
                return
            core.update_state_and_debug_dump()
            if core.is_in_reset_grace():
                self._status(painter, "SECTORS: NEW SESSION")
                return
            classes = defaultdict(dict)
            driver_map = core.driver_map()
            names = class_labels(driver_map.values())
            for idx, driver in driver_map.items():
                if core._is_safety_car(driver):
                    continue
                try:
                    cid = int(driver.get("CarClassID", -1))
                except (TypeError, ValueError):
                    continue
                if cid >= 0:
                    classes[cid][idx] = driver
            if not classes:
                self._status(painter, "SECTORS: WAITING FOR CARS")
                return
            player = core.player_idx()
            player_class = next((cid for cid, group in classes.items() if player in group), None)
            if player_class is None:
                self._status(painter, "SECTORS: WAITING FOR PLAYER CLASS")
                return
            drivers = {idx: drv for group in classes.values() for idx, drv in group.items()}
            selected, means = core.sector_history.longest_sectors(drivers)
            numbers = [core.sector_history.sector_numbers[i] for i in selected]
            self._set_sector_headers(numbers)
            compounds = core.sg("CarIdxTireCompound", []) or []

            def tyre_for(idx):
                compound = compounds[idx] if 0 <= idx < len(compounds) else None
                letter = core.tire_letter(compound)
                return letter if letter in ("H", "W") else ""

            # Rank every eligible class car before taking three from each group.
            # As in the other overlays, grouping follows the current SDK tyre.
            ranked = core.sector_history.top_last_laps(
                classes[player_class], selected, limit=len(classes[player_class]))
            groups = {tyre: [car for car in ranked if tyre_for(car["_idx"]) == tyre]
                      for tyre in ("H", "W")}
            player_tyre = tyre_for(player)
            player_car = next((car for car in ranked if car["_idx"] == player), None)
            player_rank = next((rank for rank, car in enumerate(groups.get(player_tyre, []), 1)
                                if car["_idx"] == player), "")
            player_row = self._car_row(player, drivers[player], player_tyre, player_car, player_rank)
            recent = core.sector_history.last_sector_times.get(player, {})
            player_row.update({key: format_lap_millis(recent[selected[slot]])
                               if slot < len(selected) and selected[slot] in recent else ""
                               for slot, key in enumerate(self._timing_ids)})
            player_row["_player_reference"] = True
            rows = [{"_separator": True, "label": names.get(player_class, f"CLASS {player_class}")},
                    player_row]
            active_groups = [tyre for tyre in ("H", "W") if groups[tyre]]
            display_groups = [(tyre, 3 if len(active_groups) == 2 else 5) for tyre in active_groups]
            for tyre, limit in display_groups:
                top = groups[tyre][:limit]
                rows.extend(self._car_row(car["_idx"], drivers[car["_idx"]], tyre, car, rank)
                            for rank, car in enumerate(top, 1))
                rows.extend(self._blank_slot() for _ in range(limit - len(top)))
            rows.extend(self._blank_slot() for _ in range(2 + self._ranking_slots - len(rows)))
            self._last_rows = rows
            self._last_payload = {"sector": numbers[0] if numbers else None, "sectors": numbers,
                                  "sector_selection_means": means, "ranking": "latest_complete_lap_time",
                                  "player_timing": "latest_observed_sector",
                                  "tyre_groups": [tyre for tyre, _ in display_groups],
                                  "player_row": player_row, "rows": rows}
            self.draw(painter, rows)
            core.update_state_and_debug_dump(extra={"longest_sector": self._last_payload})
        except Exception as exc:
            core._log(f"Sectors paint error: {exc!r}")
        finally:
            painter.end()
