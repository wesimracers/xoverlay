import ast
from collections import defaultdict, deque
import math
from pathlib import Path
import unittest

from headless_widgets import basic_data, core, render, set_data
from longest_sector import LongestSector
from sector_timing import SectorHistory, sector_columns


def record(history, idx, durations):
    end = 0
    crossings = {}
    for sector, duration in enumerate(durations):
        end += duration
        if sector < len(durations) - 1:
            crossings[sector] = end
    return history.record_lap(idx, 0, crossings, end, end, len(durations))


class SectorHistoryTests(unittest.TestCase):
    def test_production_tyre_codes_are_dry_h_and_wet_w(self):
        path = Path(__file__).resolve().parents[1] / "main/core.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "tire_letter")
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
        letter = namespace['tire_letter']
        self.assertEqual([letter(c) for c in (0, 1, 99, None)], ['H', 'W', '', ''])

    def test_more_than_twenty_sectors_actual_numbers_and_sum_order(self):
        history = SectorHistory()
        numbers = list(range(1, 28))
        history.configure_sectors(numbers)
        durations = [1] * 27
        durations[4], durations[14], durations[20] = 12, 10, 11
        record(history, 0, durations)
        selected, means = history.longest_sectors({0: {}})
        self.assertEqual(selected, [4, 20, 14])
        self.assertEqual([history.sector_numbers[i] for i in selected], [5, 21, 15])
        self.assertEqual(len(means), 27)
        history.configure_sectors([5, 15, 21])
        self.assertEqual(history.last_laps, {})
        record(history, 0, [60, 5, 5])
        record(history, 1, [40, 30, 20])
        record(history, 2, [45, 10, 10])
        record(history, 3, [50, 10, 10])
        selected, _ = history.longest_sectors({i: {} for i in range(4)})
        ranked = history.top_last_laps({i: {} for i in range(4)}, selected)
        self.assertEqual([history.sector_numbers[i] for i in selected], [5, 15, 21])
        self.assertEqual([r['_idx'] for r in ranked], [2, 0, 3, 1])
        self.assertEqual([r['seconds'] for r in ranked], [65, 70, 70, 90])
        self.assertEqual(history.top_cars({i: {} for i in range(4)}, 0)[0]['_idx'], 1)

    def test_complete_selected_times_required_and_fewer_real_sectors(self):
        history = SectorHistory()
        record(history, 0, [30, 20])
        self.assertEqual(history.longest_sectors({0: {}})[0], [0, 1])
        history.last_laps[1] = {'sectors': [40], 'seconds': 40}
        history.last_laps[2] = {'sectors': [20, float('nan')], 'seconds': 40}
        history.last_laps[3] = {'sectors': [20, 0], 'seconds': 40}
        self.assertEqual([r['_idx'] for r in history.top_last_laps({i: {} for i in range(4)}, [0, 1])], [0])
        history.reset()
        record(history, 0, [30])
        self.assertEqual(history.longest_sectors({0: {}})[0], [0])
        self.assertEqual(history.top_last_laps({0: {}}, [0])[0]['seconds'], 30)
        self.assertEqual(history.top_last_laps({0: {}}, []), [])

    def test_legacy_column_upgrade_keeps_config_identifiers_and_user_fields(self):
        original = [{'id': 'pos', 'label': 'POS', 'width': 42, 'enabled': True},
                    {'id': 'num', 'label': '#', 'width': 50, 'enabled': True},
                    {'id': 'sector', 'label': 'Time', 'width': 125, 'enabled': True},
                    {'id': 'tire', 'label': 'T', 'width': 60, 'enabled': True}]
        columns = sector_columns(original)
        self.assertEqual([c['id'] for c in columns],
                         ['pos', 'num', 'sector', 'sector_2', 'sector_3', 'tire'])
        self.assertEqual(columns[1]['width'], 50)
        self.assertEqual([c['label'] for c in columns][2:5], ['Setor'] * 3)
        self.assertEqual(original[2]['label'], 'Time')  # no saved-config mutation


    def test_latest_lap_replaces_fast_and_slow_history_and_changes_ranking(self):
        history = SectorHistory()
        drivers = {idx: {} for idx in range(5)}
        for _ in range(10):
            record(history, 0, [80, 10, 10])
        for idx in range(1, 5):
            record(history, idx, [10, 40, 20])
        sector, means = history.longest_sector(drivers)
        self.assertEqual(sector, 1)  # pooled laps would incorrectly choose S1
        self.assertEqual(means, [24, 34, 18])
        record(history, 0, [10, 100, 10])
        ranked = history.top_cars(drivers, sector)
        self.assertEqual([r["_idx"] for r in ranked], [1, 2, 3, 4, 0])
        self.assertEqual(history.latest_sectors(drivers)[0], [10, 100, 10])
        self.assertEqual(history.top_last_laps(drivers, [0, 1, 2])[-1]['seconds'], 120)
        record(history, 0, [10, 20, 10])
        self.assertEqual(history.top_last_laps(drivers, [0, 1, 2])[0]['seconds'], 40)
        record(history, 0, [10, 50, 10])
        self.assertEqual(history.top_last_laps(drivers, [0, 1, 2])[0]['seconds'], 70)

    def test_bad_and_partial_laps_and_clean_reset(self):
        history = SectorHistory()
        for kwargs in ({"start": None}, {"crossings": {0: 30}},
                       {"end": float("nan")}, {"lap_time": float("inf")},
                       {"crossings": {0: 30, 1: 30}}, {"lap_time": 110},
                        {"complete": False}):
            sample = dict(car_idx=0, start=0, crossings={0: 30, 1: 70},
                          end=100, lap_time=100, sector_count=3)
            sample.update(kwargs)
            self.assertFalse(history.record_lap(**sample))
        self.assertEqual(history.last_laps, {})
        record(history, 0, [60, 20, 20])
        self.assertEqual(history.longest_sector({0: {}})[0], 0)
        history.reset()
        record(history, 0, [10, 20, 70])
        self.assertEqual(history.longest_sector({0: {}})[0], 2)

    def test_rejected_latest_lap_removes_previous_valid_rank(self):
        history = SectorHistory()
        for invalid in ({'complete': False}, {'crossings': {}}, {'lap_time': 120}, {'start': None}):
            record(history, 0, [30, 40, 30])
            sample = dict(car_idx=0, start=100, crossings={0: 131, 1: 172},
                          end=200, lap_time=100, sector_count=3)
            sample.update(invalid)
            self.assertFalse(history.record_lap(**sample))
            self.assertEqual(history.top_last_laps({0: {}}, [0, 1, 2]), [])

    def test_total_lap_ranking_not_only_three_displayed_sectors(self):
        history = SectorHistory()
        record(history, 0, [25, 25, 25, 24])
        record(history, 1, [26, 26, 26, 1])
        selected, _ = history.longest_sectors({0: {}, 1: {}})
        self.assertEqual(selected, [0, 1, 2])
        self.assertEqual([r['_idx'] for r in history.top_last_laps({0: {}, 1: {}}, selected)], [1, 0])


class LongestSectorWidgetTests(unittest.TestCase):
    def setUp(self):
        self.history = getattr(core, "sector_history", None)
        core.sector_history = SectorHistory()
        self.tyres = core.tire_letter
        core.tire_letter = lambda c: {0: "H", 1: "W"}.get(c, "")
        self.widget = LongestSector()

    def tearDown(self):
        self.widget.close()
        core.sector_history = self.history
        core.tire_letter = self.tyres
        core.ir.is_connected = True

    def test_full_groups_player_outside_top_three_and_current_tyre_change(self):
        from unittest.mock import patch
        telemetry, session = basic_data()
        session['DriverInfo']['Drivers'] = [
            {'CarIdx': idx, 'CarClassID': 2 if idx == 10 else 1,
             'CarClassShortName': 'GT3', 'CarNumber': str(100 + idx)} for idx in range(11)]
        telemetry['CarIdxTireCompound'] = [0] * 5 + [1] * 4 + [99, 0]
        for idx, seconds in enumerate([90, 30, 25, 35, 40, 18, 17, 19, 20, 5, 3]):
            record(core.sector_history, idx, [seconds, 10, 20])
        set_data(telemetry, session)
        with patch.object(self.widget, '_draw_cell_text', wraps=self.widget._draw_cell_text) as draw:
            render(self.widget)
        rows = self.widget._last_rows
        self.assertEqual([r['_idx'] for r in rows[2:]], [2, 1, 3, 6, 5, 7])
        self.assertEqual([r['pos'] for r in rows[2:]], ['1', '2', '3'] * 2)
        self.assertEqual([r['tire'] for r in rows[2:]], ['H'] * 3 + ['W'] * 3)
        self.assertEqual(rows[1]['_idx'], 0)
        self.assertEqual(rows[1]['pos'], '5')
        self.assertEqual(rows[1]['num'], '100')
        self.assertEqual(rows[1]['sector'], '1:30.000')
        self.assertTrue(rows[1]['is_player'])
        # Verify rendered data sits one row above the labels, in aligned columns.
        player_cell = next(call.args[1] for call in draw.call_args_list if call.args[2] == '100')
        header_cell = next(call.args[1] for call in draw.call_args_list if call.args[2] == '#')
        self.assertEqual(player_cell.x(), header_cell.x())
        self.assertEqual(player_cell.y() + self.widget._draw_row_h, header_cell.y())
        telemetry['PlayerCarIdx'] = 5
        render(self.widget)
        self.assertEqual(self.widget._last_rows[1]['_idx'], 5)
        self.assertEqual(self.widget._last_rows[1]['pos'], '2')
        self.assertEqual(self.widget._last_rows[1]['tire'], 'W')
        # A current tyre change moves the car between groups without inventing samples.
        telemetry['CarIdxTireCompound'][2] = 1
        render(self.widget)
        self.assertEqual([r['_idx'] for r in self.widget._last_rows[2:5]], [1, 3, 4])
        self.assertEqual([r['_idx'] for r in self.widget._last_rows[5:8]], [6, 5, 7])

    def test_player_without_samples_and_unknown_or_missing_compounds(self):
        telemetry, session = basic_data()
        telemetry['CarIdxTireCompound'] = [1, 0, 99]
        record(core.sector_history, 1, [30, 10, 20])
        record(core.sector_history, 2, [25, 10, 20])
        set_data(telemetry, session)
        render(self.widget)
        player = self.widget._last_rows[1]
        self.assertEqual([player[k] for k in ('pos', 'num', 'sector', 'sector_2', 'sector_3', 'tire')],
                         ['', '1', '', '', '', 'W'])
        self.assertTrue(player['is_player'])
        self.assertEqual(self.widget._last_rows[2]['_idx'], 1)
        self.assertTrue(all(r.get('_empty') for r in self.widget._last_rows[3:]))
        record(core.sector_history, 0, [35, 10, 20])
        telemetry.pop('CarIdxTireCompound')
        render(self.widget)
        self.assertEqual(self.widget._last_rows[1]['sector'], '0:35.000')
        self.assertEqual(self.widget._last_rows[1]['tire'], '')
        self.assertEqual(self.widget._last_rows[1]['pos'], '')
        self.assertTrue(all(r.get('_empty') for r in self.widget._last_rows[2:]))

    def test_only_wet_shows_five_and_player_updates_each_sector(self):
        telemetry, session = basic_data()
        session['DriverInfo']['Drivers'] = [
            {'CarIdx': idx, 'CarClassID': 1, 'CarNumber': str(idx + 1)} for idx in range(7)]
        telemetry['CarIdxTireCompound'] = [1] * 7
        for idx, seconds in enumerate([90, 30, 25, 35, 40, 45, 50]):
            record(core.sector_history, idx, [seconds, 10, 20])
        set_data(telemetry, session)
        render(self.widget)
        self.assertEqual([r['_idx'] for r in self.widget._last_rows[2:7]], [2, 1, 3, 4, 5])
        self.assertEqual([r['tire'] for r in self.widget._last_rows[2:7]], ['W'] * 5)
        self.assertTrue(self.widget._last_rows[7]['_empty'])
        self.assertEqual(self.widget._last_payload['tyre_groups'], ['W'])
        core.sector_history.record_sector(0, 0, 23)
        render(self.widget)
        player = self.widget._last_rows[1]
        self.assertEqual([player[k] for k in self.widget._timing_ids], ['0:23.000', '0:20.000', '0:10.000'])
        self.assertEqual(player['pos'], '7')  # ranking still uses the completed lap
        record(core.sector_history, 0, [23, 10, 20])
        render(self.widget)
        self.assertEqual(self.widget._last_rows[1]['pos'], '1')
        self.assertEqual(self.widget._last_rows[2]['_idx'], 0)
        self.assertEqual(self.widget._last_rows[2]['sector'], '0:23.000')
        core.sector_history.record_lap(0, 0, {}, 53, 53, 3)
        render(self.widget)
        self.assertEqual(self.widget._last_rows[1]['pos'], '')
        self.assertEqual(self.widget._last_rows[1]['sector'], '0:23.000')
        self.assertNotIn(0, [r['_idx'] for r in self.widget._last_rows[2:] if '_idx' in r])

    def test_no_eligible_wet_shows_five_dry_and_one_empty_slot(self):
        telemetry, session = basic_data()
        session['DriverInfo']['Drivers'] = [
            {'CarIdx': idx, 'CarClassID': 2 if idx == 9 else 1,
             'CarNumber': str(idx + 1)} for idx in range(10)]
        telemetry['CarIdxTireCompound'] = [0] * 7 + [1, 99, 1]
        for idx, seconds in enumerate([90, 30, 25, 35, 40, 45, 50]):
            record(core.sector_history, idx, [seconds, 10, 20])
        record(core.sector_history, 8, [5, 10, 20])  # unknown tyre is in neither group
        record(core.sector_history, 9, [3, 10, 20])  # W in another class does not count
        set_data(telemetry, session)
        render(self.widget)
        height = self.widget.height()
        rows = self.widget._last_rows
        self.assertEqual(len(rows), 8)
        self.assertEqual([r['_idx'] for r in rows[2:7]], [2, 1, 3, 4, 5])
        self.assertEqual([r['pos'] for r in rows[2:7]], ['1', '2', '3', '4', '5'])
        self.assertEqual([r['tire'] for r in rows[2:7]], ['H'] * 5)
        self.assertTrue(rows[7]['_empty'])
        self.assertEqual(rows[1]['_idx'], 0)
        self.assertEqual(rows[1]['pos'], '7')
        self.assertEqual(self.widget._last_payload['tyre_groups'], ['H'])
        # A W car with no recorded sector data must not trigger the 3+3 layout.
        record(core.sector_history, 7, [38, 10, 20])
        render(self.widget)
        self.assertEqual([r['_idx'] for r in self.widget._last_rows[2:6]], [2, 1, 3, 7])
        self.assertTrue(all(r.get('_empty') for r in self.widget._last_rows[6:]))
        self.assertEqual(self.widget._last_payload['tyre_groups'], ['H', 'W'])
        self.assertEqual(self.widget.height(), height)
        telemetry['CarIdxTireCompound'][7] = 99
        render(self.widget)
        self.assertEqual([r['_idx'] for r in self.widget._last_rows[2:7]], [2, 1, 3, 4, 5])
        self.assertTrue(self.widget._last_rows[7]['_empty'])
        self.assertEqual(self.widget.height(), height)

    def test_sum_ranking_differs_from_race_and_single_sector_three_real_headers(self):
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        for driver in session['DriverInfo']['Drivers']:
            driver['CarClassShortName'] = 'GT3'
        telemetry['CarIdxClassPosition'] = [1, 2, 3]
        core.sector_history.configure_sectors([5, 15, 21])
        record(core.sector_history, 0, [60, 5, 5])
        record(core.sector_history, 1, [40, 30, 20])
        record(core.sector_history, 2, [45, 10, 10])
        set_data(telemetry, session)
        render(self.widget)
        self.assertEqual(self.widget.windowTitle(), 'Sectors')
        self.assertEqual(self.widget._last_rows[0]['label'], 'GT3')
        self.assertEqual(self.widget._last_payload['sectors'], [5, 15, 21])
        self.assertEqual([c['label'] for c in self.widget.columns],
                         ['POS', '#', 'Setor 5', 'Setor 15', 'Setor 21', 'T'])
        rows = [r for r in self.widget._last_rows if '_idx' in r and not r.get('_player_reference')]
        self.assertEqual([r['_idx'] for r in rows], [2, 0, 1])
        self.assertEqual([r['pos'] for r in rows], ['1', '2', '3'])
        self.assertEqual([rows[0][key] for key in ('sector', 'sector_2', 'sector_3')],
                         ['0:45.000', '0:10.000', '0:10.000'])
        self.assertEqual(len(self.widget._last_rows), 8)
        core.sector_history.reset()
        render(self.widget)
        self.assertEqual(self.widget._last_rows[0]['label'], 'GT3')
        self.assertEqual(self.widget._last_payload['sectors'], [])
        self.assertTrue(all(r.get('_empty') for r in self.widget._last_rows[2:]))
        self.assertEqual([c['label'] for c in self.widget.columns][2:5], ['Setor'] * 3)

    def test_one_or_two_sector_tracks_keep_three_columns_without_fake_numbers(self):
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        set_data(telemetry, session)
        for durations in ([40], [40, 20]):
            core.sector_history.reset()
            record(core.sector_history, 0, durations)
            render(self.widget)
            row = self.widget._last_rows[1]
            self.assertEqual(row['pos'], '1')
            self.assertEqual(row['sector_3'], '')
            self.assertEqual(self.widget.columns[4]['label'], 'Setor')
            if len(durations) == 1:
                self.assertEqual(row['sector_2'], '')
                self.assertEqual(self.widget.columns[3]['label'], 'Setor')
            self.assertEqual(len(self.widget._last_rows), 8)

    def test_player_class_top_three_per_tyre_sum_ranks_and_appearance(self):
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        drivers = session["DriverInfo"]["Drivers"]
        drivers.extend([{"CarIdx": 3, "CarClassID": 1, "CarNumber": "4"},
                        {"CarIdx": 4, "CarClassID": 2, "CarNumber": "5"},
                        {"CarIdx": 5, "CarClassID": 3, "CarNumber": "6"},
                        {"CarIdx": 6, "CarClassID": 4, "CarIsPaceCar": True},
                        {"CarIdx": 7, "CarClassID": 1, "CarNumber": "7"},
                        {"CarIdx": 8, "CarClassID": 1, "CarNumber": "8"}])
        telemetry["CarIdxTireCompound"] = [0, 1, 0, 1, 99, 0, 0, 1, 99]
        telemetry["CarIdxClassPosition"] = [8, 5, 2, 1, 4, 1, 1, 7, 9]
        for idx, seconds in enumerate([50, 40, 45, 55, 60]):
            record(core.sector_history, idx, [10, seconds, 20])
        record(core.sector_history, 6, [200, 10, 10])
        record(core.sector_history, 7, [10, 51, 20])
        record(core.sector_history, 8, [10, 53, 20])
        set_data(telemetry, session)
        render(self.widget)  # first render resizes
        image = render(self.widget)
        rows = self.widget._last_rows
        self.assertEqual(self.widget._last_payload["sector"], 2)
        self.assertEqual([r["_idx"] for r in rows if "_idx" in r and not r.get("_player_reference")], [2, 0, 1, 7, 3])
        self.assertEqual([r["pos"] for r in rows if "_idx" in r and not r.get("_player_reference")], ["1", "2", "1", "2", "3"])
        self.assertEqual([r["tire"] for r in rows if "_idx" in r and not r.get("_player_reference")], ["H", "H", "W", "W", "W"])
        self.assertEqual([r["sector"] for r in rows if "_idx" in r and not r.get("_player_reference")],
                         ["0:45.000", "0:50.000", "0:40.000", "0:51.000", "0:55.000"])
        self.assertEqual(len([r for r in rows if r.get("_separator")]), 1)
        self.assertEqual(len([r for r in rows if r.get("_empty")]), 1)
        self.assertEqual(rows[1]["_idx"], 0)
        self.assertEqual(rows[1]["pos"], "2")
        self.assertTrue(rows[1]["_player_reference"])
        self.assertEqual(image.pixelColor(4, core.PAD_Y + self.widget._draw_row_h + 2).getRgb()[:3],
                         core.CLR_PLAYER_BG.getRgb()[:3])
        self.assertEqual(image.pixelColor(4, 4).getRgb()[:3], (255, 255, 0))
        self.assertGreaterEqual(self.widget.height(), self.widget._draw_row_h * 9 + 6)
        telemetry["CarIdxClassPosition"] = [0, None, float("nan")]
        render(self.widget)
        self.assertEqual([r["pos"] for r in self.widget._last_rows if "_idx" in r and not r.get("_player_reference")], ["1", "2", "1", "2", "3"])
        self.assertEqual([c["label"] for c in self.widget.columns], ["POS", "#", "Setor 2", "Setor 3", "Setor 1", "T"])
        self.assertFalse(self.widget._uppercase_headers)

    def test_global_sector_choice_player_switch_and_unknown_player(self):
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        session["DriverInfo"]["Drivers"].append({"CarIdx": 3, "CarClassID": 2, "CarPath": "dallarap217"})
        telemetry["CarIdxTireCompound"].append(0)
        telemetry["CarIdxClassPosition"] = [2, 3, 1, 4]
        record(core.sector_history, 0, [10, 50, 20])
        record(core.sector_history, 1, [10, 40, 10])
        record(core.sector_history, 3, [10, 10, 200])
        set_data(telemetry, session)
        render(self.widget)
        self.assertEqual(self.widget._last_payload["sector"], 3)  # other class determines the sector
        self.assertEqual([r["_idx"] for r in self.widget._last_rows if "_idx" in r and not r.get("_player_reference")], [1, 0])
        telemetry["PlayerCarIdx"] = 3
        render(self.widget)
        self.assertEqual([r["_idx"] for r in self.widget._last_rows if "_idx" in r and not r.get("_player_reference")], [3])
        self.assertTrue(self.widget._last_rows[0]["label"].startswith("LMP2"))
        telemetry["PlayerCarIdx"] = 99
        render(self.widget)
        self.assertEqual(len(self.widget._last_rows), 8)
        self.assertTrue(all(r.get("_empty") for r in self.widget._last_rows[2:]))
        self.assertIn("WAITING FOR PLAYER CLASS", self.widget._last_payload["status"])

    def test_waiting_disconnect_and_recomputed_selection(self):
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        set_data(telemetry, session)
        render(self.widget)
        self.assertIsNone(self.widget._last_payload["sector"])
        self.assertTrue(self.widget._last_rows[-1]["_empty"])
        record(core.sector_history, 0, [10, 20, 70])
        render(self.widget)
        self.assertEqual(self.widget._last_payload["sector"], 3)
        core.sector_history.reset()
        render(self.widget)
        self.assertIsNone(self.widget._last_payload["sector"])
        record(core.sector_history, 0, [70, 20, 10])
        render(self.widget)
        self.assertEqual(self.widget._last_payload["sector"], 1)
        core.ir.is_connected = False
        render(self.widget)
        self.assertEqual(len(self.widget._last_rows), 8)
        self.assertTrue(all(r.get("_empty") for r in self.widget._last_rows[2:]))

    def test_six_fixed_slots_stable_capacity_widths_and_height_for_all_states(self):
        from unittest.mock import patch
        from PyQt6.QtGui import QFontMetrics
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        for driver in session["DriverInfo"]["Drivers"]:
            driver["CarClassShortName"] = "GT3"
        set_data(telemetry, session)
        self.assertEqual(len(self.widget._last_rows), 8)  # slots exist at construction
        render(self.widget)
        initial_height = self.widget.height()
        widths = [c["width"] for c in self.widget._draw_columns]
        self.assertEqual(initial_height, 9 * self.widget._draw_row_h + 2 * core.PAD_Y)

        def assert_slots(populated):
            rows = self.widget._last_rows
            self.assertEqual(len(rows), 8)
            self.assertTrue(rows[0]["_separator"])
            self.assertEqual(sum("_idx" in r for r in rows[2:]), populated)
            for row in rows[2:]:
                if row.get("_empty"):
                    self.assertEqual([row[key] for key in ("pos", "num", "sector", "sector_2", "sector_3", "tire")], [""] * 6)
            self.assertEqual(self.widget.height(), initial_height)
            self.assertEqual([c["width"] for c in self.widget._draw_columns], widths)

        assert_slots(0)
        record(core.sector_history, 0, [10, 40, 20])
        render(self.widget)
        assert_slots(1)
        record(core.sector_history, 1, [10, 39, 20])
        record(core.sector_history, 2, [10, 38, 20])
        render(self.widget)
        assert_slots(3)
        telemetry["CarIdxClassPosition"] = [888, 999, 123]
        for driver in session["DriverInfo"]["Drivers"]:
            driver["CarNumber"] = "888"
        render(self.widget)
        assert_slots(3)
        self.assertEqual(sum(c['width'] for c in self.widget._draw_columns),
                         self.widget.width() - 2 * core.PAD_X)
        core.ir.is_connected = False
        render(self.widget)
        assert_slots(0)
        core.ir.is_connected = True
        with patch.object(core, "is_in_reset_grace", return_value=True):
            render(self.widget)
            assert_slots(0)
        core.sector_history.reset()
        render(self.widget)
        assert_slots(0)
        telemetry["PlayerCarIdx"] = 99
        render(self.widget)
        assert_slots(0)
        self.assertEqual(self.widget._last_rows[0]["label"], "")

    def test_time_exceeding_one_minute_digit_remains_complete_when_width_allows(self):
        from PyQt6.QtGui import QFontMetrics
        from unittest.mock import patch
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        set_data(telemetry, session)
        record(core.sector_history, 0, [10, 600.123, 20])
        with patch.dict(core.cfg['windows']['longest_sector'], width=1000):
            render(self.widget)
        row = next(r for r in self.widget._last_rows if r.get("_idx") == 0)
        self.assertEqual(row["sector"], "10:00.123")
        self.assertEqual(row["tire"], "H")
        col = next(c for c in self.widget._draw_columns if c["id"] == "sector")
        self.assertGreaterEqual(col["width"], QFontMetrics(self.widget.font_bold).horizontalAdvance(row["sector"]) + 4)
        self.assertEqual(len(self.widget._last_rows), 8)

    def test_width_budget_odd_remainders_narrow_clipping_and_data_changes(self):
        from unittest.mock import patch
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        set_data(telemetry, session)
        record(core.sector_history, 1, [30, 40, 50])
        windows = core.cfg['windows']['longest_sector']
        saved_position = self.widget.pos()
        saved_font = self.widget.font_normal.toString()
        for width in (1, 6, 7, 37, 101, 328, 481, 1001):
            with patch.dict(windows, width=width):
                render(self.widget)
                self.assertEqual(self.widget.width(), width)
                self.assertEqual(len(self.widget._draw_columns), 6)
                self.assertEqual(sum(c['width'] for c in self.widget._draw_columns), max(0, width - 6))
                self.assertTrue(all(c['width'] >= 0 for c in self.widget._draw_columns))
                self.assertEqual(self.widget.height(), 9 * self.widget._draw_row_h + 6)
                prior_widths = [c['width'] for c in self.widget._draw_columns]
                session['DriverInfo']['Drivers'][1]['CarNumber'] = '123456789' * 20
                render(self.widget)
                self.assertEqual([c['width'] for c in self.widget._draw_columns], prior_widths)
                self.assertEqual(self.widget.pos(), saved_position)
                self.assertEqual(self.widget.font_normal.toString(), saved_font)
        # The very long number cannot change pixels in the adjacent tyre cell.
        with patch.dict(windows, width=481):
            image = render(self.widget)
            session['DriverInfo']['Drivers'][1]['CarNumber'] = '2'
            short_image = render(self.widget)
            columns = self.widget._draw_columns
            x = core.PAD_X + sum(c['width'] for c in columns[:-1])
            y = core.PAD_Y + 3 * self.widget._draw_row_h
            for px in range(x + 2, x + columns[-1]['width'] - 2):
                for py in range(y + 2, y + self.widget._draw_row_h - 2):
                    self.assertEqual(image.pixelColor(px, py), short_image.pixelColor(px, py))

    def test_manager_width_apply_save_reload_preserves_anchor_font_and_six_rows(self):
        import copy, json, tempfile
        import manager
        from unittest.mock import patch
        telemetry, session = basic_data()
        telemetry["CarIdxTireCompound"] = [0, 0, 0]
        set_data(telemetry, session)
        config = copy.deepcopy(core.cfg)
        config['windows']['longest_sector'].update(x=345, y=678, width=480, font_size=10)
        meta = next(m for m in manager.WIDGET_DEFS if m['key'] == 'longest_sector')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'overlay.json'
            with patch.object(core, 'cfg', config), patch.object(core, 'save_cfg',
                      side_effect=lambda: path.write_text(json.dumps(core.cfg), encoding='utf-8')):
                widget = LongestSector()
                dialog = manager.WidgetConfigDialog(None, meta, widget)
                try:
                    font = widget.font_normal.toString()
                    height = widget.height()
                    dialog._inputs['_win_width'].setValue(481)
                    dialog._save_and_close()
                    self.assertEqual(widget.width(), 481)  # immediate before the next paint
                    self.assertEqual(widget.height(), height)
                    render(widget)
                    record(core.sector_history, 0, [10, 40, 20])
                    render(widget)
                    self.assertEqual(widget.width(), 481)
                    self.assertEqual(widget.height(), height)
                    self.assertEqual((widget.x(), widget.y()), (345, 678))
                    self.assertEqual(widget.font_normal.toString(), font)
                    saved = json.loads(path.read_text(encoding='utf-8'))
                    self.assertEqual(saved['windows']['longest_sector']['width'], 481)
                    with patch.object(core, 'cfg', saved):
                        restarted = LongestSector()
                        try:
                            self.assertEqual(restarted.width(), 481)
                            self.assertEqual(restarted.height(), height)
                            self.assertEqual((restarted.x(), restarted.y()), (345, 678))
                            render(restarted)
                            self.assertEqual(sum(c['width'] for c in restarted._draw_columns), 475)
                            self.assertEqual(len(restarted._last_rows), 8)
                        finally:
                            restarted.close()
                finally:
                    dialog.close()
                    widget.close()


class CoreSectorIntegrationTests(unittest.TestCase):
    """Run the production telemetry block without core's disk/network startup."""

    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "main/core.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                       and functions["_is_safety_car"].end_lineno < n.lineno < functions["init_start_positions"].lineno]
        timing_block = next(n for n in functions["update_state_and_debug_dump"].body
                            if isinstance(n, ast.Try) and isinstance(n.body[0], ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == "onpit" for t in n.body[0].targets))
        errors = []
        self.data = {"WeekendInfo": {"TrackID": 1}, "SessionTime": 0,
                     "SessionInfo": {"SplitTimeInfo": {"Sectors": [
                         {"SectorStartPct": 0}, {"SectorStartPct": .3}, {"SectorStartPct": .7}]}},
                     "CarIdxOnPitRoad": [False], "CarIdxLapCompleted": [1],
                     "CarIdxLastLapTime": [100], "CarIdxLapDistPct": [0],
                     "CarIdxIncidentCount": [0]}
        ns = {"defaultdict": defaultdict, "deque": deque, "SectorHistory": SectorHistory,
              "math": math, "DEBUG": False, "_log": errors.append,
              "time": __import__("time"), "sg": lambda k, default=None: self.data.get(k, default),
              "session_time": lambda: self.data["SessionTime"], "player_idx": lambda: 0,
              "driver_map": lambda: {}, "session_best_lap_update": lambda *a: None,
              "_safe_int": lambda v, default: int(v)}
        extracted = [functions[name] for name in ("_init_sectors", "_normalize_lap_time_sec", "avg_sec_filtered", "avg_sec", "reset_lap_history", "best_last", "session_best_lap", "fmt_time_1")]
        exec(compile(ast.Module(body=assignments + extracted, type_ignores=[]), str(path), "exec"), ns)
        tick = ast.FunctionDef(name="tick", args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                               body=[timing_block], decorator_list=[])
        exec(compile(ast.fix_missing_locations(ast.Module(body=[tick], type_ignores=[])), str(path), "exec"), ns)
        self.ns, self.errors = ns, errors

    def drive(self, until=300, incident=False, pit=False):
        for step in range(until * 2 + 1):
            t = step / 2
            elapsed = t % 100
            pct = (.3 * elapsed / 20 if elapsed < 20 else
                   .3 + .4 * (elapsed - 20) / 50 if elapsed < 70 else
                   .7 + .3 * (elapsed - 70) / 30)
            self.data.update(SessionTime=t, CarIdxLapCompleted=[1 + int(t // 100)],
                             CarIdxLapDistPct=[pct], CarIdxOnPitRoad=[pit and 140 <= t < 150],
                             CarIdxIncidentCount=[int(incident and t >= 200)])
            self.ns["tick"]()
        self.assertEqual(self.errors, [])

    def test_full_observed_laps_only_and_track_change(self):
        self.drive()
        history = self.ns["sector_history"]
        self.assertEqual(history.last_laps[0], {'seconds': 100, 'sectors': [20, 50, 30]})
        self.data["WeekendInfo"]["TrackID"] = 2
        self.data["SessionInfo"]["SplitTimeInfo"]["Sectors"] = [{"SectorStartPct": .2}, {"SectorStartPct": .6}]
        self.ns["tick"]()
        self.assertEqual(history.last_laps, {})
        self.assertEqual(self.ns["_sector_pcts"], [.2, .6])

    def test_incident_on_finish_counts_for_sectors_but_not_clean_avg(self):
        self.drive(until=200, incident=True)
        self.assertEqual(self.ns["sector_history"].last_laps[0], {'seconds': 100, 'sectors': [20, 50, 30]})
        self.assertEqual(self.ns["sector_history"].last_sector_times[0], {0: 20, 1: 50, 2: 30})
        self.assertEqual(list(self.ns['lap_hist'][0]), [100])  # earlier lap only

    def test_pit_laps_count_for_sectors_but_not_clean_avg(self):
        self.drive(pit=True)
        self.assertEqual(self.ns["sector_history"].last_laps[0], {'seconds': 100, 'sectors': [20, 50, 30]})
        self.assertEqual(list(self.ns['lap_hist'][0]), [100])  # earlier lap only

    def test_native_root_split_info_and_missing_samples(self):
        self.data["SplitTimeInfo"] = self.data["SessionInfo"].pop("SplitTimeInfo")
        self.drive()
        self.assertEqual(self.ns["sector_history"].last_laps[0]['sectors'], [20, 50, 30])
        self.data.update(SessionTime=303, CarIdxLapDistPct=[.05])
        self.ns["tick"]()
        self.assertNotIn(0, self.ns["_sf_cross_time"])

    def test_native_noncontiguous_sdk_identifiers_and_many_boundaries(self):
        sectors = [{'SectorNum': i * 2, 'SectorStartPct': i / 27} for i in range(27)]
        self.data['SplitTimeInfo'] = {'Sectors': list(reversed(sectors))}
        self.ns['_init_sectors']()
        self.assertEqual(self.ns['_sector_pcts'], [i / 27 for i in range(1, 27)])
        self.assertEqual(self.ns['sector_history'].sector_numbers, [i * 2 + 1 for i in range(27)])
        record(self.ns['sector_history'], 0, [2] * 27)
        self.data['WeekendInfo']['TrackID'] = 2
        self.data['SplitTimeInfo'] = {'Sectors': [
            {'SectorNum': 20, 'SectorStartPct': .7},
            {'SectorNum': 4, 'SectorStartPct': 0},
            {'SectorNum': 14, 'SectorStartPct': .3}]}
        self.ns['_init_sectors']()
        self.assertEqual(self.ns['sector_history'].last_laps, {})
        self.assertEqual(self.ns['sector_history'].sector_numbers, [5, 15, 21])

    def test_sector_capture_updates_before_lap_is_completed(self):
        self.drive(until=170)
        history = self.ns['sector_history']
        self.assertEqual(history.last_laps, {})
        self.assertEqual(history.last_sector_times[0], {0: 20, 1: 50})
        self.assertEqual(history.longest_sectors({0: {}})[0], [1, 0])
        self.assertEqual(history.last_laps, {})

    def test_manager_columns_timer_and_legacy_config_defaults(self):
        import manager
        from unittest.mock import patch
        from PyQt6.QtCore import QTimer
        from rpm_state import seed_rpm_config
        namespace = {"CONFIG_FILE": str(Path(__file__).resolve().parents[1] / "main/factory-overlay.json"), "os": __import__("os"),
                     "json": __import__("json"), "SECTOR_COLUMNS": manager.SECTOR_COLUMNS,
                     "sector_columns": sector_columns, "seed_rpm_config": seed_rpm_config}
        path = Path(__file__).resolve().parents[1] / "main/core.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        load = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "load_cfg")
        exec(compile(ast.Module(body=[load], type_ignores=[]), str(path), "exec"), namespace)
        with patch.object(namespace["json"], "load", return_value={"windows": {"standings": {"x": 99}}}):
            config = namespace["load_cfg"]()
        self.assertEqual(config["windows"]["standings"]["x"], 99)
        self.assertEqual([c["label"] for c in config["longest_sector_settings"]["columns"]],
                         ["POS", "#", "Setor", "Setor", "Setor", "T"])
        meta = next(m for m in manager.WIDGET_DEFS if m["key"] == "longest_sector")
        self.assertEqual(meta['label'], 'Sectors')
        widget = LongestSector()
        timer = QTimer()
        with patch.object(manager.core, "cfg", config), patch.object(manager.core, "save_cfg"):
            dialog = manager.WidgetConfigDialog(None, meta, widget, timer)
            try:
                self.assertIsNotNone(dialog._col_ed)
                dialog._inputs["_cfg_update_ms"].setValue(175)
                dialog._save_and_close()
                self.assertEqual(timer.interval(), 175)
                self.assertEqual(len(widget.columns), 6)
            finally:
                dialog.close()
                widget.close()


if __name__ == "__main__":
    unittest.main()
