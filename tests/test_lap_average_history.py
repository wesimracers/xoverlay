import unittest
from unittest.mock import patch

import test_longest_sector as sector_tests
from headless_widgets import core, basic_data, set_data, render, Standings, Relative


class LapAverageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.harness = sector_tests.CoreSectorIntegrationTests(methodName="runTest")
        self.harness.setUp()
        self.ns, self.data = self.harness.ns, self.harness.data
        self.data["CarIdxLastLapTime"] = [-1]
        self.data["CarIdxBestLapTime"] = [100]
        self.ns["tick"]()

    def drive_laps(self, durations, incident_lap=None, pit_lap=None):
        current_time, incidents = 0, 0
        for lap, duration in enumerate(durations, 1):
            for step in range(1, duration * 2 + 1):
                elapsed = step / 2
                finishing = elapsed == duration
                if finishing and lap == incident_lap:
                    incidents += 1
                self.data.update(SessionTime=current_time + elapsed,
                                 CarIdxLapCompleted=[lap + 1 if finishing else lap],
                                 CarIdxLapDistPct=[0 if finishing else elapsed / duration],
                                 CarIdxOnPitRoad=[lap == pit_lap and 20 <= elapsed < 30],
                                 CarIdxIncidentCount=[incidents])
                if finishing:
                    self.data["CarIdxLastLapTime"] = [duration]
                self.ns["tick"]()
            current_time += duration
        self.assertEqual(self.harness.errors, [])

    def test_rolling_average_uses_multiple_completed_laps_last_uses_latest(self):
        self.drive_laps([100, 102, 104])
        self.assertEqual(list(self.ns["lap_hist"][0]), [100, 102, 104])
        self.assertEqual(self.ns["avg_sec_filtered"](0, 5, 5), 102)
        self.assertEqual(self.ns["avg_sec_filtered"](0, 2, 5), 103)
        self.assertEqual(self.ns["best_last"](0)[1], "1:44.0")

    def test_finish_incident_excludes_that_lap_and_next_clean_lap_is_kept(self):
        self.drive_laps([100, 102, 104], incident_lap=2)
        self.assertEqual(list(self.ns["lap_hist"][0]), [100, 104])
        self.assertEqual(self.ns["avg_sec_filtered"](0, 5, 5), 102)
        self.assertEqual(self.ns["best_last"](0)[1], "1:44.0")

    def test_pit_inlap_outlap_and_filtered_slow_laps(self):
        self.drive_laps([100, 101, 102, 103], pit_lap=2)
        self.assertEqual(list(self.ns["lap_hist"][0]), [100, 103])
        self.ns["lap_hist"][0].append(200)
        self.assertEqual(self.ns["avg_sec_filtered"](0, 5, 5), 101.5)
        self.assertEqual(self.ns["best_last"](0)[1], "1:43.0")

    def test_session_reset_rejects_initial_stale_lap_and_invalid_last(self):
        self.drive_laps([100, 102])
        self.ns["reset_lap_history"]()
        self.assertIsNone(self.ns["avg_sec_filtered"](0, 5, 5))
        self.data.update(SessionTime=300, CarIdxLapCompleted=[7], CarIdxLapDistPct=[.5],
                         CarIdxLastLapTime=[80])
        self.ns["tick"]()
        self.assertIsNone(self.ns["avg_sec_filtered"](0, 5, 5))
        self.data.update(SessionTime=301, CarIdxLapCompleted=[8], CarIdxLapDistPct=[0],
                         CarIdxLastLapTime=[100])
        self.ns["tick"]()
        self.assertEqual(self.ns["avg_sec_filtered"](0, 5, 5), 100)
        self.assertEqual(self.ns["best_last"](0)[1], "1:40.0")
        self.data["CarIdxLastLapTime"] = [float("nan")]
        self.assertEqual(self.ns["best_last"](0)[1], "")

    def test_rounding_can_legitimately_hide_small_average_last_differences(self):
        self.ns["lap_hist"][0].extend([100.04, 100.03])
        average = self.ns["avg_sec_filtered"](0, 5, 5)
        self.data["CarIdxLastLapTime"] = [100.03]
        self.assertNotEqual(average, 100.03)
        self.assertEqual(self.ns["fmt_time_1"](average), self.ns["best_last"](0)[1])

    def test_both_widgets_show_average_delta_and_independent_last_lap(self):
        self.ns["lap_hist"][0].extend([100, 102, 104])
        self.ns["lap_hist"][1].extend([100, 101, 102])
        self.data["CarIdxBestLapTime"] = [100, 100, 100]
        self.data["CarIdxLastLapTime"] = [104, 102, 100]
        telemetry, session = basic_data()
        set_data(telemetry, session)
        with patch.object(core, "avg_sec_filtered", self.ns["avg_sec_filtered"]), patch.object(core, "best_last", self.ns["best_last"]):
            for factory in (Standings, Relative):
                widget = factory()
                try:
                    render(widget)
                    row = next(r for r in widget._last_rows if r.get("_idx") == 1)
                    self.assertEqual(row["avg"], "1.0")
                    self.assertEqual(row["last"], "1:42.0")
                    self.assertEqual(widget.avg_laps, 5)
                finally:
                    widget.close()


if __name__ == "__main__":
    unittest.main()
