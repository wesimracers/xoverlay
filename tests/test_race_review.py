import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "main"))

from blacklist import BlacklistStore, normalize_user_id
from race_review import RaceMonitor, race_key
from headless_widgets import APP, Relative, basic_data, core, render, set_data
from race_review_ui import DriverReviewDialog
from PyQt6.QtWidgets import QPushButton


class BlacklistTests(unittest.TestCase):
    def test_manual_ids_and_event_selection_persist_without_overwriting_others(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blacklist.json"
            path.write_text('{"ids": [123, 900], "note": "keep"}', encoding="utf-8")
            store = BlacklistStore(path)
            self.assertEqual(store.current_ids(), {123, 900})
            store.save_selection({123, 456}, {456}, "789")
            self.assertEqual(store.read_ids(), {456, 789, 900})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["note"], "keep")
            path.write_text('{"ids": [456, 789, 900, 321]}', encoding="utf-8")
            self.assertEqual(store.current_ids(), {456, 789, 900, 321})
            store.save_selection({456}, {456})
            self.assertEqual(store.read_ids(), {456, 789, 900, 321})

    def test_invalid_ids_and_broken_manual_file_are_not_overwritten(self):
        self.assertIsNone(normalize_user_id(0))
        self.assertIsNone(normalize_user_id("abc"))
        self.assertEqual(normalize_user_id(" 123 "), 123)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blacklist.json"
            store = BlacklistStore(path)
            with self.assertRaises(ValueError):
                store.save_selection(set(), set(), "wrong")
            self.assertFalse(path.exists())
            path.write_text('{"ids": [123, "bad"]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                store.save_selection(set(), set(), "456")
            self.assertEqual(path.read_text(encoding="utf-8"), '{"ids": [123, "bad"]}')


class RaceMonitorTests(unittest.TestCase):
    signature = (100, 200, 300, 2, "Race", "Track")

    def test_roster_survives_dropout_restart_and_finish_shows_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "race_review_state.json"
            monitor = RaceMonitor(path)
            first = [
                {"CarIdx": 0, "UserID": 123, "UserName": "Ana", "CarNumber": "23"},
                {"CarIdx": 1, "UserID": 456, "UserName": "Bia", "CarNumber": "77"},
                {"CarIdx": 2, "CarIsPaceCar": True, "UserName": "Safety", "CarNumber": "0"},
            ]
            self.assertIsNone(monitor.poll(True, self.signature, 4, first, now=0))
            self.assertIsNone(monitor.poll(True, self.signature, 4, first[:1], now=1))
            restarted = RaceMonitor(path)
            self.assertIsNone(restarted.poll(True, self.signature, 5, first[:1], now=2))
            event = restarted.poll(True, self.signature, 6, first[:1], now=3)
            self.assertEqual({p["id"] for p in event["participants"]}, {123, 456})
            self.assertEqual(len(restarted.pending), 1)
            self.assertIsNone(restarted.poll(True, self.signature, 6, first, now=4))
            restarted.mark_reviewed(event["key"])
            self.assertEqual(RaceMonitor(path).pending, [])
            self.assertEqual(race_key(self.signature), "sub:200|num:2")

    def test_corrupt_state_retries_after_the_file_is_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "race_review_state.json"
            path.write_text("{", encoding="utf-8")
            monitor = RaceMonitor(path)
            self.assertTrue(monitor.last_error)
            self.assertIsNone(monitor.poll(True, self.signature, 4, [], now=1))
            self.assertTrue(monitor.last_error)
            path.write_text('{"active": null, "pending": [], "handled": []}\n', encoding="utf-8")
            driver = [{"CarIdx": 1, "UserID": 55, "UserName": "Ana", "CarNumber": "5"}]
            self.assertIsNone(monitor.poll(True, self.signature, 4, driver, now=2))
            self.assertEqual(monitor.last_error, "")
            self.assertIsNotNone(monitor.active)

    def test_disconnect_finishes_after_grace_without_losing_participants(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = RaceMonitor(Path(directory) / "state.json", disconnect_grace_s=2)
            driver = [{"CarIdx": 4, "UserID": 888, "UserName": "Jo", "CarNumber": "8"}]
            monitor.poll(True, self.signature, 4, driver, now=10)
            self.assertIsNone(monitor.poll(False, now=11))
            self.assertIsNone(monitor.poll(False, now=12))
            event = monitor.poll(False, now=13)
            self.assertEqual(event["participants"][0]["id"], 888)
            self.assertIsNone(monitor.poll(False, now=20))

    def test_practice_is_ignored_and_transition_finishes_race_once(self):
        with tempfile.TemporaryDirectory() as directory:
            monitor = RaceMonitor(Path(directory) / "state.json")
            driver = [{"CarIdx": 4, "UserID": 888, "UserName": "Jo", "CarNumber": "8"}]
            practice = (100, 200, 300, 1, "Practice", "Track")
            self.assertIsNone(monitor.poll(True, practice, 4, driver, now=1))
            self.assertIsNone(monitor.poll(True, self.signature, 4, driver, now=2))
            event = monitor.poll(True, practice, 2, [], now=3)
            self.assertEqual(event["participants"][0]["id"], 888)
            self.assertIsNone(monitor.poll(True, practice, 2, [], now=4))
            self.assertEqual(len(monitor.pending), 1)


class ReviewUiAndRelativeTests(unittest.TestCase):
    def test_relative_number_column_migrates_once_then_respects_user_choice(self):
        old_settings = copy.deepcopy(core.cfg["relative_settings"])
        old_window = copy.deepcopy(core.cfg["windows"]["relative"])
        first = second = None
        try:
            settings = core.cfg["relative_settings"]
            settings.pop("marked_num_column_ready", None)
            number_col = next(col for col in settings["columns"] if col["id"] == "num")
            number_col.update(enabled=False, width=25)
            first = Relative()
            self.assertTrue(number_col["enabled"])
            self.assertGreater(number_col["width"], 25)
            self.assertTrue(settings["marked_num_column_ready"])
            number_col["enabled"] = False
            second = Relative()
            self.assertFalse(number_col["enabled"])
        finally:
            if first is not None:
                first.close()
            if second is not None:
                second.close()
            core.cfg["relative_settings"] = old_settings
            core.cfg["windows"]["relative"] = old_window

    def test_manage_screen_can_remove_an_id_and_add_another(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BlacklistStore(Path(directory) / "blacklist.json")
            store.save_selection(set(), set(), "111")
            store.save_selection(set(), set(), "222")
            dialog = DriverReviewDialog(store)
            try:
                self.assertEqual(dialog.windowTitle(), "Manage marked drivers")
                self.assertEqual([dialog.table.horizontalHeaderItem(i).text() for i in range(3)],
                                 ["Car number", "Driver name", "Mark"])
                self.assertIn("Save", [button.text() for button in dialog.findChildren(QPushButton)])
                self.assertEqual(dialog.table.rowCount(), 2)
                dialog._checkboxes[0][1].setChecked(False)
                dialog.manual_id.setText("333")
                dialog._save()
                self.assertEqual(store.read_ids(), {222, 333})
            finally:
                dialog.close()
                dialog.deleteLater()
                APP.processEvents()

    def test_manager_opens_review_only_on_click_during_and_after_race(self):
        import manager

        with tempfile.TemporaryDirectory() as directory:
            store = BlacklistStore(Path(directory) / "blacklist.json")
            monitor = RaceMonitor(Path(directory) / "state.json")
            telemetry, session = basic_data()
            session["DriverInfo"]["Drivers"][0].update(UserID=101, UserName="Ana")
            telemetry["DriverInfo"] = session["DriverInfo"]
            set_data(telemetry, session)
            old_store = getattr(core, "blacklist_store", None)
            old_signature = getattr(core, "_session_signature", None)
            core.blacklist_store = store
            core._session_signature = lambda: (10, 20, 30, 1, "Race", "Track")
            window = manager.ManagerWindow({}, {}, monitor)
            try:
                self.assertIn("Review race drivers / marked IDs",
                              [button.text() for button in window.findChildren(QPushButton)])
                window._race_review_timer.stop()
                telemetry["SessionState"] = 4
                window._poll_race_review()
                self.assertIsNone(window._review_dialog)
                window.open_race_review_manager()
                self.assertEqual(window._review_dialog.table.rowCount(), 3)
                window._review_dialog.reject()
                APP.processEvents()
                self.assertIsNone(window._review_dialog)
                telemetry["SessionState"] = 5
                window._poll_race_review()
                self.assertIsNone(window._review_dialog)
                telemetry["SessionState"] = 6
                window._poll_race_review()
                APP.processEvents()
                self.assertIsNone(window._review_dialog)
                self.assertEqual(len(monitor.pending), 1)
                window.open_race_review_manager()
                self.assertIsNotNone(window._review_dialog)
                self.assertEqual(window._review_dialog.table.rowCount(), 3)
                window._review_dialog._checkboxes[0][1].setChecked(True)
                window._review_dialog._save()
                self.assertEqual(store.read_ids(), {101})
                self.assertEqual(monitor.pending, [])
                APP.processEvents()
                self.assertIsNone(window._review_dialog)
                window.open_race_review_manager()
                self.assertEqual(window._review_dialog.table.rowCount(), 3)
                self.assertTrue(window._review_dialog._checkboxes[0][1].isChecked())
                self.assertEqual(len(RaceMonitor(Path(directory) / "state.json").review_event()["participants"]), 3)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()
                if old_store is None:
                    del core.blacklist_store
                else:
                    core.blacklist_store = old_store
                if old_signature is None:
                    del core._session_signature
                else:
                    core._session_signature = old_signature

    def test_pending_race_does_not_open_review_on_manager_startup(self):
        import manager

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            monitor = RaceMonitor(state_path)
            drivers = [{"CarIdx": 0, "UserID": 101, "UserName": "Ana", "CarNumber": "23"}]
            monitor.poll(True, (10, 20, 30, 1, "Race", "Track"), 4, drivers, now=1)
            monitor.poll(True, (10, 20, 30, 1, "Race", "Track"), 6, drivers, now=2)
            self.assertEqual(len(monitor.pending), 1)
            old_store = getattr(core, "blacklist_store", None)
            core.blacklist_store = BlacklistStore(Path(directory) / "blacklist.json")
            window = manager.ManagerWindow({}, {}, RaceMonitor(state_path))
            try:
                window._race_review_timer.stop()
                APP.processEvents()
                self.assertIsNone(window._review_dialog)
                window.open_race_review_manager()
                self.assertEqual(window._review_dialog.table.rowCount(), 1)
            finally:
                window.close()
                window.deleteLater()
                APP.processEvents()
                if old_store is None:
                    del core.blacklist_store
                else:
                    core.blacklist_store = old_store

    def test_table_save_manual_id_and_relative_match_user_id_across_car_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BlacklistStore(Path(directory) / "blacklist.json")
            event = {"key": "race:1", "participants": [
                {"id": 222, "number": "23", "name": "Ana"},
                {"id": None, "number": "90", "name": "Sem ID"},
            ]}
            dialog = DriverReviewDialog(store, event)
            try:
                self.assertEqual(dialog.table.rowCount(), 2)
                self.assertFalse(dialog._checkboxes[1][1].isEnabled())
                dialog._checkboxes[0][1].setChecked(True)
                dialog.manual_id.setText("333")
                dialog._save()
                self.assertTrue(dialog.saved)
                self.assertEqual(store.read_ids(), {222, 333})
            finally:
                dialog.close()
                dialog.deleteLater()
                APP.processEvents()

            telemetry, session = basic_data()
            drivers = session["DriverInfo"]["Drivers"]
            drivers[0].update(UserID=111, CarNumber="23")
            drivers[1].update(UserID=222, CarNumber="23")
            drivers[2].update(UserID=333, CarNumber="44")
            set_data(telemetry, session)
            old_blacklist_ids = core.blacklist_ids
            core.blacklist_ids = store.current_ids
            widget = Relative()
            try:
                render(widget)
                numbers = {row["_idx"]: row["num"] for row in widget._last_rows if row["_idx"] is not None}
                self.assertEqual(numbers[0], "23")
                self.assertEqual(numbers[1], "23!")
                self.assertEqual(numbers[2], "44!")
                drivers[1]["CarNumber"] = "99"
                render(widget)
                numbers = {row["_idx"]: row["num"] for row in widget._last_rows if row["_idx"] is not None}
                self.assertEqual(numbers[1], "99!")
            finally:
                core.blacklist_ids = old_blacklist_ids
                widget.close()


if __name__ == "__main__":
    unittest.main()
