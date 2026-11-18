"""Exercise real Qt widgets and the event loop; never open native display adapters."""

import os
import threading
import time
import unittest
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

from spectra.backends.demo import DemoBackend
from spectra.studio import Studio

if find_spec("PySide6") is None:
    raise unittest.SkipTest("Настольные тесты требуют установки .[desktop]")

# This is only the Qt platform plugin for tests. Production chooses the native platform.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from spectra.desktop.preview import SCENES, lut, reference, tinted  # noqa: E402
from spectra.desktop.ui import theme  # noqa: E402
from spectra.desktop.window import Window  # noqa: E402


class NativeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
        theme(cls.app)

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def until(self, predicate, diagnostics=None):
        deadline = time.monotonic() + 8
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(5)
        if not predicate():
            self.fail(diagnostics() if diagnostics else "Timed out waiting for the Qt event loop")

    def open(self, factory=None, *, wait=True):
        w = Window(factory or (lambda: Studio(demo=True, directory=self.tmp.name)))
        w.resize(1160, 760)
        w.show()

        def cleanup():
            self.until(lambda: not w.busy)
            w.close()
            w.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup)
        if wait:
            self.until(lambda: not w.busy)
        return w

    def test_preview_is_read_only_and_changes_with_the_draft(self):
        w = self.open()
        u = w.workspace
        self.assertTrue(w.state["demo"])
        self.assertEqual(len(u.devices), 2)
        self.assertEqual(u.number.value(), 70)
        self.assertFalse(u.undo.isEnabled())
        self.assertTrue(all(d.findChildren(type(u.count))[0].height() > 0 for d in u.devices))
        u.devices[1].click()
        self.assertEqual(u.scope.currentData(), "demo-lg")
        u.profiles["warm"].click()
        self.assertEqual(u.metrics[0].text(), "5000 K")
        u.number.setValue(33)
        u.paint_draft()
        first = u.view.after
        self.assertEqual(u.brightness.value(), 33)
        u.brightness.setValue(65)
        u.paint_draft()
        self.assertNotEqual(u.view.after, first)
        u.scene.setCurrentText(SCENES[2])
        u.paint_draft()
        self.assertNotEqual(first, u.view.after)
        u.compare.click()
        self.assertFalse(u.view.split)
        u.compare.click()
        QTest.keyClick(u.view, Qt.Key.Key_Home)
        QTest.keyClick(u.view, Qt.Key.Key_Right)
        self.assertEqual(u.view.value(), 1)
        u.auto.click()
        self.assertEqual(u.profile, "standard")
        self.assertEqual(u.number.value(), 85)
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_targeted_apply_history_and_undo_even_after_selection_changes(self):
        w = self.open()
        u = w.workspace
        before = deepcopy(w.state["monitors"])
        u.devices[1].click()
        u.profiles["cinema"].click()
        u.number.setValue(41)
        u.apply.click()
        self.assertTrue(w.busy)
        self.assertFalse(u.apply.isEnabled())
        self.until(lambda: not w.busy)
        self.assertEqual(w.state["monitors"][0], before[0])
        self.assertEqual(w.state["monitors"][1]["brightness"], 41)
        self.assertEqual(w.state["history"][0]["ids"], ["demo-lg"])
        u.devices[0].click()
        w.switch_page(1)
        self.assertEqual(w.history.table.rowCount(), 1)
        w.history.undo.click()
        self.until(lambda: not w.busy)
        self.assertEqual(w.state["monitors"], before)
        self.assertFalse(w.history.undo.isEnabled())
        self.assertEqual(w.state["history"][0]["status"], "undone")

    def test_all_displays_and_recovery_after_restart(self):
        w = self.open()
        w.workspace.number.setValue(52)
        w.workspace.apply.click()
        self.until(lambda: not w.busy)
        self.assertEqual([m["brightness"] for m in w.state["monitors"]], [52, 52])
        w.close()
        again = self.open()
        self.assertTrue(again.workspace.undo.isEnabled())
        again.workspace.undo.click()
        self.until(lambda: not again.busy)
        self.assertEqual([m["brightness"] for m in again.state["monitors"]], [46, 94])

    def test_real_mode_requires_confirmation_for_apply_and_undo(self):
        hw = DemoBackend()
        original = deepcopy(hw.ramps)
        w = self.open(lambda: Studio(directory=self.tmp.name, factory=lambda: hw))
        self.assertFalse(w.state["demo"])
        w.confirm = Mock(return_value=False)
        w.workspace.apply.click()
        self.assertEqual(hw.ramps, original)
        self.assertFalse(w.busy)
        w.confirm.assert_called_once()
        w.confirm.return_value = True
        w.workspace.apply.click()
        self.until(lambda: not w.busy)
        self.assertNotEqual(hw.ramps, original)
        w.confirm.return_value = False
        w.undo()
        self.assertIsNotNone(w.state["undoId"])
        self.assertFalse(w.busy)
        w.confirm.return_value = True
        w.undo()
        self.until(lambda: not w.busy)
        self.assertEqual(hw.ramps, original)

    def test_unplug_does_not_silently_select_remaining_outputs(self):
        hw = DemoBackend()
        w = self.open(lambda: Studio(directory=self.tmp.name, factory=lambda: hw))
        u = w.workspace
        u.devices[1].click()
        hw.devices = hw.devices[:1]
        w.scan.click()
        self.until(lambda: not w.busy)
        self.assertEqual(u.selected, [])
        self.assertFalse(u.apply.isEnabled())
        u.devices[0].click()
        self.assertTrue(u.apply.isEnabled())
        hw.devices = []
        w.scan.click()
        self.until(lambda: not w.busy)
        self.assertTrue(u.no_devices.isVisible())
        self.assertFalse(u.apply.isEnabled())

    def test_failure_is_visible_and_retryable(self):
        def broken():
            raise OSError("Нет доступа к дисплеям")

        w = self.open(broken)
        self.assertTrue(w.alert.isVisible())
        self.assertIn("Нет доступа", w.alert.text())
        self.assertTrue(w.scan.isEnabled())
        self.assertFalse(w.workspace.apply.isEnabled())

    def test_close_during_io_defers_destruction_without_blocking_ui(self):
        started = threading.Event()
        release = threading.Event()

        def delayed():
            started.set()
            release.wait(3)
            return Studio(demo=True, directory=self.tmp.name)

        w = self.open(delayed, wait=False)
        self.addCleanup(release.set)
        self.until(started.is_set)
        self.assertTrue(w.busy)
        self.assertFalse(w.close())
        self.assertTrue(w.isVisible())
        release.set()
        self.until(lambda: not w.isVisible())
        self.assertFalse(w.thread.isRunning())

    def test_small_window_scrolls_without_hiding_controls_horizontally(self):
        w = self.open()
        w.resize(625, 540)
        self.app.processEvents()
        self.assertTrue(w.workspace.compact)

        def widths():
            parts = {
                "page": w.scroll.widget(),
                "left": w.workspace.left,
                "form": w.workspace.form,
                "card": w.workspace.devices[0],
                "title": w.title,
                "scan": w.scan,
            }
            hints = {key: widget.minimumSizeHint().width() for key, widget in parts.items()}
            return f"Viewport: {w.scroll.viewport().width()}, minimum widths: {hints}"

        self.until(lambda: w.scroll.horizontalScrollBar().maximum() == 0, widths)
        grid = w.workspace.devices_grid
        self.assertIs(grid.itemAtPosition(1, 0).widget(), w.workspace.devices[1])
        self.assertGreater(w.scroll.verticalScrollBar().maximum(), 0)
        w.scroll.ensureWidgetVisible(w.workspace.apply)
        self.assertFalse(w.workspace.apply.visibleRegion().isEmpty())
        # The hidden calibration form should not extend the empty history page.
        calibration_overflow = w.scroll.verticalScrollBar().maximum()
        w.switch_page(1)
        self.until(lambda: w.scroll.verticalScrollBar().maximum() < calibration_overflow)
        w.switch_page(0)
        w.resize(1160, 760)
        self.until(lambda: not w.workspace.compact)
        self.assertIs(grid.itemAtPosition(0, 1).widget(), w.workspace.devices[1])

    def test_preview_luts_are_interpolated_and_clamped(self):
        self.assertEqual(lut([0, 1], 1), bytes(range(256)))
        self.assertEqual(lut([0, 1], 2)[150], 255)
        for scene in SCENES:
            image = tinted(scene, [[0, 1]] * 3)
            self.assertEqual(image, reference(scene))
