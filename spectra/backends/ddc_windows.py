"""Win32 Monitor Configuration API. Restrict each handle to its exact GDI output."""

import ctypes as C
from contextlib import contextmanager
from ctypes import wintypes as W

from .backlight import Backlight
from .base import DisplayError


class MonitorInfo(C.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("screen", W.RECT),
        ("work", W.RECT),
        ("flags", W.DWORD),
        ("device", W.WCHAR * 32),
    ]


class PhysicalMonitor(C.Structure):
    _fields_ = [("handle", W.HANDLE), ("description", W.WCHAR * 128)]


class WindowsBacklight:
    def __init__(self, displays):
        self.displays = displays
        self.u, self.dx = displays.u, C.WinDLL("dxva2")
        self.callback = C.WINFUNCTYPE(W.BOOL, W.HANDLE, W.HDC, C.POINTER(W.RECT), W.LPARAM)
        self.u.EnumDisplayMonitors.argtypes = [W.HDC, C.POINTER(W.RECT), self.callback, W.LPARAM]
        self.u.GetMonitorInfoW.argtypes = [W.HANDLE, C.POINTER(MonitorInfo)]
        self.dx.GetNumberOfPhysicalMonitorsFromHMONITOR.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        self.dx.GetPhysicalMonitorsFromHMONITOR.argtypes = [
            W.HANDLE,
            W.DWORD,
            C.POINTER(PhysicalMonitor),
        ]
        self.dx.DestroyPhysicalMonitors.argtypes = [W.DWORD, C.POINTER(PhysicalMonitor)]
        self.dx.GetMonitorBrightness.argtypes = [W.HANDLE, *([C.POINTER(W.DWORD)] * 3)]
        self.dx.SetMonitorBrightness.argtypes = [W.HANDLE, W.DWORD]

    @contextmanager
    def physical(self, monitor):
        handles = []

        @self.callback
        def collect(hmon, dc, rect, data):
            info = MonitorInfo(size=C.sizeof(MonitorInfo))
            if self.u.GetMonitorInfoW(hmon, C.byref(info)) and info.device == monitor.connector:
                handles.append(hmon)
            return True

        self.u.EnumDisplayMonitors(None, None, collect, 0)
        count = W.DWORD()
        if (
            len(handles) != 1
            or not self.dx.GetNumberOfPhysicalMonitorsFromHMONITOR(handles[0], C.byref(count))
            or count.value != 1
        ):
            yield None
            return
        monitors = (PhysicalMonitor * 1)()
        if not self.dx.GetPhysicalMonitorsFromHMONITOR(handles[0], 1, monitors):
            yield None
            return
        try:
            yield monitors[0].handle
        finally:
            self.dx.DestroyPhysicalMonitors(1, monitors)

    def read(self, monitor):
        low, value, high = W.DWORD(), W.DWORD(), W.DWORD()
        with self.physical(monitor) as handle:
            if handle and self.dx.GetMonitorBrightness(
                handle, C.byref(low), C.byref(value), C.byref(high)
            ):
                if low.value <= value.value <= high.value and low.value < high.value:
                    return Backlight(low.value, value.value, high.value)
        return None

    def write(self, monitor, target):
        if not any(m.id == monitor.id and m.adjustable for m in self.displays.scan()):
            raise DisplayError("Физический монитор больше не подключён к выбранному выходу.")
        with self.physical(monitor) as handle:
            if not handle or not self.dx.SetMonitorBrightness(handle, target.current):
                raise DisplayError(
                    f"{monitor.name}: монитор не принял значение подсветки. Проверьте DDC/CI в экранном меню."
                )
