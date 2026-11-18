import hashlib
import json
import unittest
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from spectra.backends.backlight import Backlight
from spectra.backends.base import DisplayError
from spectra.backends.ddc_linux import LinuxBacklight
from spectra.backends.demo import DemoBackend
from spectra.color import make_ramp
from spectra.studio import Studio
from tests.test_color import edid


class VirtualLight:
    def __init__(self, initial):
        self.values = dict(initial)

    def read(self, monitor):
        return self.values.get(monitor.id)

    def write(self, monitor, value):
        self.values[monitor.id] = value


class BrightnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hw = DemoBackend()
        self.a, self.b = self.hw.scan()
        self.raw = {self.a.id: Backlight(5, 137, 255), self.b.id: Backlight(10, 74, 110)}
        self.hw.backlight = VirtualLight(self.raw)
        self.ramps = deepcopy(self.hw.ramps)
        self.app = Studio(directory=self.tmp.name, factory=lambda: self.hw)

    def test_native_percent_uses_raw_range_without_double_dimming(self):
        s = self.app.apply([self.a.id], "warm", 30)
        self.assertEqual(self.hw.backlight.values[self.a.id].current, 80)
        self.assertEqual(self.hw.backlight.values[self.b.id], self.raw[self.b.id])
        self.assertEqual(self.hw.ramps[self.a.id], make_ramp(self.a, "warm", 100, 256))
        self.assertEqual(s["monitors"][0]["brightnessMode"], "backlight")
        self.assertEqual(s["monitors"][0]["brightness"], 30)
        restarted = Studio(directory=self.tmp.name, factory=lambda: self.hw)
        restarted.undo(s["undoId"])
        self.assertEqual(self.hw.backlight.values, self.raw)
        self.assertEqual(self.hw.ramps, self.ramps)

    def test_mixed_hardware_and_software_brightness(self):
        self.hw.backlight.values.pop(self.b.id)
        s = self.app.apply([self.a.id, self.b.id], "standard", 40)
        self.assertEqual([m["brightnessMode"] for m in s["monitors"]], ["backlight", "signal"])
        self.assertEqual([m["brightness"] for m in s["monitors"]], [40, 40])
        self.assertEqual(self.hw.ramps[self.b.id], make_ramp(self.b, "standard", 40, 256))
        self.app.undo(s["undoId"])
        self.assertEqual(self.hw.ramps, self.ramps)

    def test_second_backlight_write_failure_restores_both_luts_and_raw_values(self):
        real = self.hw.backlight.write

        def fail(m, target):
            saved = json.loads(self.app.file.read_text())["entries"][-1]
            self.assertEqual(saved["backlights"][self.a.id]["current"], 137)
            real(m, target)
            if m.id == self.b.id and target != self.raw[self.b.id]:
                raise DisplayError("DDC failure")

        with (
            patch.object(self.hw.backlight, "write", side_effect=fail),
            self.assertRaises(DisplayError),
        ):
            self.app.apply([self.a.id, self.b.id], "cinema", 29)
        self.assertEqual(self.hw.backlight.values, self.raw)
        self.assertEqual(self.hw.ramps, self.ramps)
        self.assertEqual(self.app.state()["history"][0]["status"], "aborted")

    def test_undo_waits_for_original_backlight_range(self):
        key = self.app.apply([self.a.id], "standard", 38)["undoId"]
        self.hw.backlight.values[self.a.id] = Backlight(0, 33, 100)
        with self.assertRaisesRegex(DisplayError, "DDC/CI"):
            self.app.undo(key)
        self.assertEqual(self.app.state()["undoId"], key)

    def test_monitor_rejecting_a_brightness_write_is_not_success(self):
        with (
            patch.object(self.hw.backlight, "write", return_value=None),
            self.assertRaisesRegex(DisplayError, "не подтверждено"),
        ):
            self.app.apply([self.a.id], "cinema", 39)
        self.assertEqual(self.hw.ramps, self.ramps)


class DdcMappingTests(unittest.TestCase):
    def test_exact_edid_to_bus_and_terse_output(self):
        with TemporaryDirectory() as folder:
            drm = Path(folder)
            port = drm / "card0-DP-1"
            port.mkdir()
            raw = bytes(edid())
            (port / "edid").write_bytes(raw)
            # Resolve a real directory named i2c-7 without needing symlink
            # privileges on Windows CI, where the parser can still be tested.
            transport = LinuxBacklight()
            transport.command = "ddcutil"
            transport.drm = drm
            m = replace(
                DemoBackend().scan()[0], id="x11-" + hashlib.sha256(b"DP-1" + raw).hexdigest()[:20]
            )
            bus = drm / "i2c-7"
            with (
                patch.object(Path, "resolve", return_value=bus),
                patch.object(
                    transport, "run", return_value=Mock(returncode=0, stdout="VCP 10 C 137 255\n")
                ) as run,
            ):
                self.assertEqual(transport.read(m), Backlight(0, 137, 255))
                run.assert_called_with("7", "getvcp", "10")
                transport.write(m, Backlight(0, 77, 255))
                run.assert_called_with("7", "setvcp", "10", "77")
                other = drm / "card0-HDMI-1"
                other.mkdir()
                (other / "edid").write_bytes(raw)
                self.assertIsNone(transport.read(m))
                with self.assertRaises(DisplayError):
                    transport.write(m, Backlight(0, 74, 255))
