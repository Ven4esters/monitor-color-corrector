import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from spectra.backends.base import DisplayError
from spectra.backends.demo import DemoBackend
from spectra.studio import Studio


class StudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.hw = DemoBackend()
        self.studio = Studio(directory=self.directory, factory=lambda: self.hw)
        self.ids = list(self.studio.monitors)
        self.original = deepcopy(self.hw.ramps)

    def test_single_target_does_not_touch_its_neighbor(self):
        a, b = self.ids
        state = self.studio.apply([b], "warm", 36)
        self.assertEqual(self.hw.ramps[a], self.original[a])
        self.assertNotEqual(self.hw.ramps[b], self.original[b])
        self.assertEqual(state["history"][0]["names"], ["LG 27UL850"])
        self.assertNotIn("before", state["history"][0])
        self.studio.undo(state["undoId"])
        self.assertEqual(self.hw.ramps, self.original)

    def test_same_target_brightness_different_per_display_luts(self):
        s = self.studio.apply(self.ids, "standard", 63)
        self.assertEqual([m["brightness"] for m in s["monitors"]], [63, 63])
        self.assertNotEqual(*self.hw.ramps.values())

    def test_preview_and_refresh_never_write_or_create_journal(self):
        with patch.object(self.hw, "write", side_effect=AssertionError("Unexpected write")):
            self.studio.refresh()
            s = self.studio.state()
            self.assertEqual(set(s["monitors"][0]["curves"]), set(s["profiles"]))
        self.assertFalse(self.studio.file.exists())

    def test_recommendations_do_not_dim_again_with_each_apply(self):
        original = self.studio.state()["recommendations"]
        for profile in ("warm", "warm", "cinema", "standard"):
            state = self.studio.apply(self.ids, profile, original["all"][profile])
            self.assertEqual(state["recommendations"], original)

    def test_undo_is_last_operation_not_reset_to_identity(self):
        first = self.studio.apply([self.ids[0]], "cinema", 75)["undoId"]
        middle = deepcopy(self.hw.ramps)
        last = self.studio.apply(self.ids, "warm", 40)["undoId"]
        with self.assertRaises(DisplayError):
            self.studio.undo(first)
        self.studio.undo(last)
        self.assertEqual(self.hw.ramps, middle)
        self.studio.undo(first)
        self.assertEqual(self.hw.ramps, self.original)
        self.assertIsNone(self.studio.state()["undoId"])

    def test_journal_survives_restart_and_preserves_custom_ramps(self):
        key = self.studio.apply(self.ids, "warm", 40)["undoId"]
        restarted = Studio(directory=self.directory, factory=lambda: self.hw)
        self.assertEqual(restarted.state()["undoId"], key)
        restarted.undo(key)
        self.assertEqual(self.hw.ramps, self.original)

    def test_write_ahead_snapshot_before_first_write_and_group_rollback(self):
        real = self.hw.write
        hit = False

        def fail_once(m, ramp):
            nonlocal hit
            saved = json.loads(self.studio.file.read_text())["entries"][-1]
            self.assertEqual(saved["before"], self.original)
            real(m, ramp)
            if m.id == self.ids[1] and not hit:
                hit = True
                raise DisplayError("Второй дисплей отклонил запись")

        with (
            patch.object(self.hw, "write", side_effect=fail_once),
            self.assertRaisesRegex(DisplayError, "восстановлены"),
        ):
            self.studio.apply(self.ids, "cinema", 54)
        self.assertEqual(self.hw.ramps, self.original)
        self.assertEqual(self.studio.state()["history"][0]["status"], "aborted")

    def test_no_write_if_snapshot_cannot_be_saved(self):
        with (
            patch.object(self.studio, "persist", side_effect=DisplayError("Нет места")),
            patch.object(self.hw, "write") as write,
        ):
            with self.assertRaises(DisplayError):
                self.studio.apply(self.ids, "standard", 55)
            write.assert_not_called()
        self.assertEqual(self.studio.entries, [])

    def test_silent_driver_failure_is_not_success(self):
        with (
            patch.object(self.hw, "write", return_value=None),
            self.assertRaisesRegex(DisplayError, "не подтвердил"),
        ):
            self.studio.apply(self.ids, "warm", 10)
        self.assertEqual(self.studio.state()["history"][0]["status"], "aborted")

    def test_interrupted_rollback_remains_recoverable(self):
        real = self.hw.write

        def fail(m, ramp):
            if m.id == self.ids[1]:
                raise DisplayError("Выход временно недоступен")
            real(m, ramp)

        with patch.object(self.hw, "write", side_effect=fail), self.assertRaises(DisplayError):
            self.studio.apply(self.ids, "warm", 41)
        state = self.studio.state()
        self.assertTrue(state["recovery"])
        with self.assertRaisesRegex(DisplayError, "откат"):
            self.studio.apply(self.ids, "warm", 42)
        restarted = Studio(directory=self.directory, factory=lambda: self.hw)
        restarted.undo(state["undoId"])
        self.assertEqual(self.hw.ramps, self.original)
        self.assertFalse(restarted.state()["recovery"])

    def test_process_exit_after_snapshot_before_completion(self):
        with (
            patch.object(self.hw, "write", side_effect=SystemExit(1)),
            self.assertRaises(SystemExit),
        ):
            self.studio.apply(self.ids, "standard", 72)
        restarted = Studio(directory=self.directory, factory=lambda: self.hw)
        s = restarted.state()
        self.assertTrue(s["recovery"])
        self.assertEqual(s["history"][0]["status"], "pending")
        restarted.undo(s["undoId"])
        self.assertEqual(self.hw.ramps, self.original)

    def test_disconnected_targets_block_apply_and_undo(self):
        key = self.studio.apply(self.ids, "cinema", 40)["undoId"]
        applied = deepcopy(self.hw.ramps)
        with patch.object(self.hw, "scan", return_value=self.hw.devices[:1]):
            with self.assertRaises(DisplayError):
                self.studio.apply(self.ids, "warm", 45)
            with self.assertRaises(DisplayError):
                self.studio.undo(key)
        self.assertEqual(self.hw.ramps, applied)
        self.studio.undo(key)
        self.assertEqual(self.hw.ramps, self.original)

    def test_invalid_requests_do_not_write(self):
        for ids, p, v in [
            ([], "standard", 30),
            (["missing"], "warm", 30),
            (self.ids, "wrong", 40),
            (self.ids, "warm", 101),
            (self.ids, "standard", True),
            (self.ids, "warm", -1),
            (self.ids, [], 70),
            ([self.ids[0]] * 2, "standard", 44),
            (None, "cinema", 60),
        ]:
            with self.assertRaises(DisplayError):
                self.studio.apply(ids, p, v)
        self.assertEqual(self.hw.ramps, self.original)

    def test_no_devices_falls_back_to_explicit_demo(self):
        with patch.object(self.hw, "scan", return_value=[]):
            app = Studio(directory=self.directory, factory=lambda: self.hw)
            self.assertTrue(app.state()["demo"])
        app.refresh()
        self.assertFalse(app.state()["demo"])

    def test_demo_is_persistent_and_isolated_from_hardware(self):
        def forbidden():
            raise AssertionError("Hardware probed in forced demo")

        app = Studio(demo=True, directory=self.directory, factory=forbidden)
        record = app.apply(self.ids, "standard", 39)["undoId"]
        restarted = Studio(demo=True, directory=self.directory, factory=forbidden)
        self.assertEqual(restarted.state()["monitors"][0]["brightness"], 39)
        restarted.undo(record)
        self.assertEqual(self.hw.ramps, self.original)
        self.assertFalse((self.directory / "displays.json").exists())

    def test_malformed_journal_is_not_overwritten(self):
        self.studio.file.write_text("{damaged")
        with self.assertRaises(DisplayError):
            Studio(directory=self.directory, factory=lambda: self.hw)
        self.assertEqual(self.studio.file.read_text(), "{damaged")

    def test_corrupt_hardware_journal_cannot_leak_demo_history_to_hardware(self):
        with patch.object(self.hw, "scan", return_value=[]):
            app = Studio(directory=self.directory, factory=lambda: self.hw)
            app.apply(self.ids, "warm", 42)
        path = self.directory / "displays.json"
        path.write_text('{"version":1,"entries":[{}]}')
        with self.assertRaises(DisplayError):
            app.refresh()
        self.assertTrue(app.state()["demo"])
        self.assertEqual(path.read_text(), '{"version":1,"entries":[{}]}')
        self.assertEqual(self.hw.ramps, self.original)
