"""ABI-facing tests use real ctypes buffers but never open a physical display."""

import ctypes as C
import os
import sys
import unittest
from contextlib import nullcontext
from unittest.mock import Mock, patch

from spectra.backends.base import DisplayError, Monitor


@unittest.skipUnless(sys.platform.startswith("linux"), "RandR adapter is Linux-only")
class RandRTests(unittest.TestCase):
    def setUp(self):
        from spectra.backends.linux import Gamma, LinuxBackend

        self.hw = LinuxBackend.__new__(LinuxBackend)
        self.hw.r = Mock()
        self.hw.connection = lambda: nullcontext(1)
        self.hw.resolve = lambda _d, _m: 19
        self.m = Monitor("id", "model", "DP-1", 1920, 1080, 60, True)
        self.n = 17
        self.buffer = Gamma(self.n, *[(C.c_ushort * self.n)() for _ in range(3)])
        self.ptr = C.pointer(self.buffer)
        self.hw.r.XRRGetCrtcGammaSize.return_value = self.n
        self.hw.r.XRRAllocGamma.return_value = self.ptr
        self.hw.r.XRRGetCrtcGamma.return_value = self.ptr

    def test_exact_driver_capacity_and_per_channel_copy(self):
        table = [[i * 3000 + c * 11 for i in range(self.n)] for c in range(3)]
        self.hw.write(self.m, table)
        self.hw.r.XRRSetCrtcGamma.assert_called_once_with(1, 19, self.ptr)
        self.assertEqual(self.hw.read(self.m), table)
        self.assertEqual(self.hw.r.XRRFreeGamma.call_count, 2)

    def test_rejects_changed_gamma_capacity(self):
        with self.assertRaises(DisplayError):
            self.hw.write(self.m, [[0, 65535]] * 3)
        self.hw.r.XRRSetCrtcGamma.assert_not_called()

    def test_no_hardware_writes_under_wayland(self):
        from spectra.backends.linux import LinuxBackend

        with (
            patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}),
            self.assertRaisesRegex(DisplayError, "Wayland"),
        ):
            LinuxBackend()


@unittest.skipUnless(sys.platform == "win32", "Win32 ABI")
class GdiTests(unittest.TestCase):
    def test_native_structure_sizes(self):
        from spectra.backends.windows import DevMode, DisplayDevice

        self.assertEqual(C.sizeof(DevMode), 220)
        self.assertEqual(C.sizeof(DisplayDevice), 840)

    def test_per_output_dc_and_round_trip(self):
        from spectra.backends.windows import WindowsBackend

        hw = WindowsBackend.__new__(WindowsBackend)
        hw.g = Mock()
        hw.g.CreateDCW.return_value = 123
        m = Monitor("id", "Test", "\\\\.\\DISPLAY2", 1920, 1080, 60, False)
        hw.scan = lambda: [m]
        table = [[i * 250 + c for i in range(256)] for c in range(3)]
        buffer = bytearray(1536)

        def write(dc, ptr):
            self.assertEqual(dc, 123)
            buffer[:] = C.string_at(ptr, len(buffer))
            return 1

        def read(dc, ptr):
            C.memmove(ptr, bytes(buffer), len(buffer))
            return 1

        hw.g.SetDeviceGammaRamp.side_effect = write
        hw.g.GetDeviceGammaRamp.side_effect = read
        hw.write(m, table)
        self.assertEqual(hw.read(m), table)
        hw.g.CreateDCW.assert_called_with("DISPLAY", m.connector, None, None)
        self.assertEqual(hw.g.DeleteDC.call_count, 2)
