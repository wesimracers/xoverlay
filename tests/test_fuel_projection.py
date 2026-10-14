import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))
from fuel_projection import project_finish, fuel_required, refuel_display


class FuelProjectionTests(unittest.TestCase):
    def project(self, **kwargs):
        args = dict(player_completed=10, player_position=.5, player_lap_time=100,
                    leader_completed=10, leader_position=.6, leader_lap_time=100)
        args.update(kwargs)
        return project_finish(**args)

    def test_timed_race_includes_final_finish_line_distance(self):
        result = self.project(time_remaining=100)
        self.assertEqual(result["finish_lap"], 12)
        self.assertEqual(result["laps_left"], 1.5)
        self.assertEqual(fuel_required(result["laps_left"], 3, .5), 5)

    def test_lap_race_removes_driven_half_lap(self):
        result = self.project(total_laps=12, time_remaining=12000)
        self.assertEqual(result["laps_left"], 1.5)

    def test_lead_lap_driver_is_not_underfuelled_for_predicted_lapping(self):
        result = self.project(total_laps=173, player_lap_time=105)
        self.assertEqual(result["finish_lap"], 173)

    def test_mixed_class_lap_cap_uses_current_progress_and_finish_time(self):
        result = self.project(total_laps=12, player_completed=5, player_lap_time=200,
                              same_class=False)
        self.assertEqual(result["finish_lap"], 7)

    def test_real_sdk_extended_remaining_includes_current_lap(self):
        result = self.project(player_completed=22, leader_completed=22, total_laps=173,
                              laps_remaining=151)
        self.assertEqual(result["finish_lap"], 173)
        result = self.project(player_completed=22, leader_completed=22, laps_remaining=151)
        self.assertEqual(result["finish_lap"], 173)

    def test_zero_timer_still_finishes_current_lap(self):
        result = self.project(time_remaining=0)
        self.assertEqual(result["laps_left"], .5)

    def test_multiclass_player_crosses_before_leader_must_do_extra_lap(self):
        result = self.project(player_position=.95, player_lap_time=120,
                              leader_position=.8, leader_lap_time=90, time_remaining=10)
        self.assertEqual(result["finish_lap"], 12)
        self.assertAlmostEqual(result["laps_left"], 1.05)

    def test_multiclass_player_crosses_after_leader_finishes(self):
        result = self.project(player_position=.5, player_lap_time=120,
                              leader_position=.8, leader_lap_time=90, time_remaining=10)
        self.assertEqual(result["laps_left"], .5)

    def test_lapped_car_projected_from_current_progress(self):
        result = self.project(player_completed=5, player_position=.5, player_lap_time=110,
                              leader_completed=10, leader_position=.6, total_laps=12)
        self.assertEqual(result["finish_lap"], 7)
        self.assertEqual(result["laps_left"], 1.5)

    def test_timer_can_end_lap_capped_race_early(self):
        self.assertEqual(self.project(total_laps=100, time_remaining=20)["finish_lap"], 11)

    def test_nonlinear_position_phase_used_for_finish_time(self):
        result = self.project(player_position=.5, player_phase=.8,
                              leader_position=.6, leader_phase=.9, time_remaining=12)
        self.assertEqual(result["laps_left"], 1.5)

    def test_personal_finish_and_white_flags(self):
        self.assertEqual(self.project(player_finished=True)["laps_left"], 0)
        self.assertEqual(self.project(player_white=True)["laps_left"], .5)
        self.assertEqual(self.project(leader_finished=True)["laps_left"], .5)

    def test_missing_sentinel_nonfinite_data(self):
        self.assertIsNone(self.project(total_laps=32767, time_remaining=math.inf))
        self.assertIsNone(self.project(player_position=-1, total_laps=12))
        self.assertIsNone(self.project(player_position=math.nan, total_laps=12))
        self.assertIsNone(fuel_required(1, 0, .5))
        self.assertEqual(refuel_display(None), "—")

    def test_measured_current_burn_instead_of_uniform_distance(self):
        self.assertEqual(fuel_required(1.5, 4, .5, position=.5, burned_this_lap=3), 5.5)
        self.assertEqual(fuel_required(1.5, 4, .5, position=.5, burned_this_lap=5), 4.5)

    def test_round_refuel_up_and_no_reserve_after_finish(self):
        self.assertEqual(refuel_display(.49), "1")
        self.assertEqual(refuel_display(3.1), "4")
        self.assertEqual(refuel_display(3), "3")
        self.assertEqual(fuel_required(0, 4, .5), 0)


if __name__ == "__main__":
    unittest.main()
