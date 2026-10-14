import unittest

from headless_widgets import Relative, Fuel, basic_data, set_data, render, core


class WidgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.telemetry, self.session = basic_data()
        set_data(self.telemetry, self.session)

    def test_relative_draws_iso_codes_and_same_class_model_gap(self):
        widget = Relative()
        try:
            render(widget)
            rows = {r["_idx"]: r for r in widget._last_rows if r["_idx"] is not None}
            self.assertEqual(rows[0]["flag"], "DE")
            self.assertEqual(rows[1]["flag"], "GB")
            self.assertEqual(rows[2]["flag"], "NG")
            self.assertEqual(rows[1]["int"], "3.0")
            self.assertEqual(rows[1]["_method"], "player_model_profile")
            # Lap counts affect number decorations, never physical ordering.
            self.telemetry["CarIdxLapCompleted"][1] = 8
            render(widget)
            rows2 = [r for r in widget._last_rows if r["_idx"] == 1]
            self.assertAlmostEqual(rows2[0]["_int_sec"], 3)
            self.assertGreater(rows2[0]["_dd_frac"], 0)
        finally:
            widget.close()

    def make_fuel(self):
        widget = Fuel()
        widget._last_sig = core._SESSION_SIG[0]
        widget._last_reset_epoch = core._RESET_EPOCH[0]
        widget.hist.append(3)
        widget.last_lap = 10
        widget.last_fuel = 4.5
        widget._first_lap_seen = True
        widget.reserve = .5
        return widget

    def test_fuel_live_refill_and_final_crossing(self):
        self.telemetry.update(CarIdxLapDistPct=[.5,.55,.6], CarIdxEstTime=[50,66,60])
        widget = self.make_fuel()
        try:
            render(widget)
            self.assertEqual(widget._last_payload["race_laps_left"], 1.5)
            self.assertEqual(widget._last_payload["refuel"], 2)
            self.telemetry["CarIdxOnPitRoad"][0] = True
            self.telemetry["FuelLevel"] = 8
            render(widget)
            self.assertEqual(widget._last_payload["refuel"], 0)
            self.telemetry["SessionState"] = 5
            render(widget)
            self.assertEqual(widget._last_payload["race_laps_left"], .5)
            self.telemetry["CarIdxLapCompleted"][0] = 11
            self.telemetry["CarIdxLapDistPct"][0] = .01
            render(widget)
            self.assertEqual(widget._last_payload["race_laps_left"], 0)
        finally:
            widget.close()

    def test_practice_has_no_race_refuel_plan(self):
        self.session["SessionInfo"]["Sessions"][0]["SessionType"] = "Practice"
        widget = self.make_fuel()
        try:
            render(widget)
            self.assertIsNone(widget._last_payload["refuel"])
        finally:
            widget.close()

    def test_midlap_join_is_not_accepted_as_full_lap_consumption(self):
        self.telemetry["CarIdxLapDistPct"][0] = .05
        widget = Fuel()
        try:
            render(widget)
            self.telemetry["CarIdxLapCompleted"][0] = 11
            self.telemetry["CarIdxLapDistPct"][0] = .001
            self.telemetry["FuelLevel"] = 1
            render(widget)
            self.assertEqual(widget._last_payload["accepted_lap_samples"], 0)
            self.assertEqual(widget._last_payload["last_lap_reject_reason"], "partial_first_lap")
        finally:
            widget.close()

    def test_fuel_last_and_avg_display_after_fast_sampler_crosses_line(self):
        self.telemetry["FuelLevel"] = 10.0
        self.telemetry["CarIdxLapDistPct"][0] = 0.0
        widget = Fuel()
        drawn = []
        widget._draw_row = lambda _painter, cells: drawn.append({key: text for key, text, _color in cells})
        try:
            widget.sample_fast()
            render(widget)  # initial 0.00 values become visible
            self.telemetry["CarIdxLapCompleted"][0] = 11
            self.telemetry["CarIdxLapDistPct"][0] = 0.01
            self.telemetry["FuelLevel"] = 8.0
            widget.sample_fast()  # lap is recorded between paints
            widget.sample_fast()  # next fast tick clears the one-frame lap flag
            render(widget)
            self.assertEqual(widget._last_payload["accepted_lap_samples"], 1)
            self.assertEqual(drawn[-1]["last"], "LAST 2.00")
            self.assertEqual(drawn[-1]["avg"], f"AVG {2 * (1 + widget.extra_pct / 100):.2f}")
            self.telemetry["FuelLevel"] = 7.8
            widget.sample_fast()
            render(widget)
            self.assertEqual(drawn[-1]["last"], "LAST 2.00")
            self.telemetry["CarIdxLapCompleted"][0] = 12
            self.telemetry["FuelLevel"] = 5.0
            widget.sample_fast()
            widget.sample_fast()
            render(widget)
            self.assertEqual(widget._last_payload["accepted_lap_samples"], 2)
            self.assertEqual(drawn[-1]["last"], "LAST 3.00")
            expected_avg = widget._percentile([2.0, 3.0], widget.percentile)
            self.assertEqual(drawn[-1]["avg"], f"AVG {expected_avg * (1 + widget.extra_pct / 100):.2f}")
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
