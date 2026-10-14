import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from relative_timing import RelativeTiming, track_position


def driver(model="a", lap=100, cls=1):
    return {"CarPath": model, "CarClassEstLapTime": lap, "CarClassID": cls}


class RelativeTimingTests(unittest.TestCase):
    def setUp(self):
        self.engine = RelativeTiming()

    def update(self, positions, estimates, drivers=None, **kwargs):
        self.engine.update(0, drivers or {0: driver(), 1: driver()}, positions,
                           estimates, kwargs.pop("surfaces", [3] * len(positions)), **kwargs)

    def test_gap_between_matches_player_and_other_pairs(self):
        self.update([.4, .5, .52], [35, 45, 47], {0: driver(), 1: driver(), 2: driver()})
        self.assertEqual(self.engine.gap_between(0, 1)[0], self.engine.gap(1)[0])
        self.assertAlmostEqual(self.engine.gap_between(1, 2)[0], 2)

    def test_same_model_uses_live_clock(self):
        self.update([.4, .41], [35, 38])
        gap, debug = self.engine.gap(1)
        self.assertEqual(gap, 3)
        self.assertEqual(debug["source"], "same_model_live")

    def test_start_finish_both_directions(self):
        self.update([.99, .01], [99, 1])
        self.assertAlmostEqual(self.engine.gap(1)[0], 2)
        self.update([.01, .99], [1, 99])
        self.assertAlmostEqual(self.engine.gap(1)[0], -2)

    def test_slow_sector_is_not_clipped_or_wrapped_by_time(self):
        self.update([.1, .5], [5, 70])
        self.assertEqual(self.engine.gap(1)[0], 65)
        self.update([.5, .1], [70, 5])
        self.assertEqual(self.engine.gap(1)[0], -65)

    def test_same_class_different_models_use_player_curve(self):
        drivers = {0: driver(), 1: driver("b", 120), 2: driver()}
        self.update([.40, .41, .42], [35, 50, 41], drivers)
        gap, debug = self.engine.gap(1)
        self.assertAlmostEqual(gap, 3)
        self.assertEqual(debug["source"], "player_model_profile")

    def test_other_class_uses_same_player_clock(self):
        drivers = {0: driver(), 1: driver("b", 120, 2), 2: driver()}
        self.update([.42, .41, .40], [41, 50, 35], drivers)
        self.assertAlmostEqual(self.engine.gap(1)[0], -3)

    def test_coincident_models_never_create_phantom_gap(self):
        for cls in (1, 2):
            self.update([.4, .4], [35, 55], {0: driver(), 1: driver("b", 120, cls)})
            self.assertEqual(self.engine.gap(1)[0], 0)

    def test_cold_cache_is_explicit_approximation(self):
        self.update([.4, .41], [35, 55], {0: driver(), 1: driver("b", 120)})
        gap, debug = self.engine.gap(1)
        self.assertAlmostEqual(gap, 1)
        self.assertTrue(debug["approximate"])

    def test_curve_interpolates_both_sides_of_finish(self):
        drivers = {0: driver(), 1: driver("b", 120), 2: driver()}
        self.update([.99, .01, .02], [99, 40, 2], drivers)
        self.assertAlmostEqual(self.engine.gap(1)[0], 2)

    def test_invisible_and_nonfinite_cars_excluded(self):
        for invalid in (-1, math.nan, math.inf, 1.1, None):
            self.update([.4, invalid], [35, 38])
            self.assertIsNone(self.engine.gap(1)[0])
            self.assertIsNone(track_position(invalid))
        self.update([.4, .41], [35, 38], surfaces=[3, -1])
        self.assertIsNone(self.engine.gap(1)[0])

    def test_bad_estimates_fall_back_without_nan_or_sign_flip(self):
        for invalid in (math.nan, math.inf, -1, 0, 1000, 34):
            self.update([.4, .41], [35, invalid])
            gap, _ = self.engine.gap(1)
            self.assertTrue(math.isfinite(gap))
            self.assertGreaterEqual(gap, 0)

    def test_cache_resets_for_clock_track_session_and_time_rewind(self):
        for change in ("lap", "track", "session", "rewind"):
            self.engine.reset()
            drivers = {0: driver(), 1: driver("b", 120), 2: driver()}
            self.update([.4, .41, .42], [35, 50, 41], drivers,
                        session_key="one", session_time=10, track_length_m=4000)
            self.assertEqual(self.engine.gap(1)[1]["source"], "player_model_profile")
            if change == "lap":
                drivers[0] = driver(lap=101)
            self.update([.4, .41, -1], [35, 50, -1], drivers,
                        session_key="two" if change == "session" else "one",
                        session_time=9 if change == "rewind" else 11,
                        track_length_m=5000 if change == "track" else 4000)
            self.assertTrue(self.engine.gap(1)[1]["approximate"], change)

    def test_missing_sdk_lap_does_not_wrap_with_actual_lap(self):
        self.update([.99, .01], [99, 1], {0: driver(lap=None), 1: driver(lap=None)},
                    fallback_lap_time=110)
        self.assertAlmostEqual(self.engine.gap(1)[0], 2.2)
        self.assertTrue(self.engine.gap(1)[1]["approximate"])

    def test_pit_cars_remain_visible(self):
        self.update([.4, .41], [35, 38], surfaces=[3, 1])
        self.assertEqual(self.engine.gap(1)[0], 3)


if __name__ == "__main__":
    unittest.main()
