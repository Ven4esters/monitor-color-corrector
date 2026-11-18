"""Win32 GDI adapter, one display DC per active output; no global desktop DC."""

import ctypes as C
import hashlib
import winreg
from contextlib import contextmanager
from ctypes import wintypes as W

from .base import DisplayError, Monitor
from .ddc_windows import WindowsBacklight
from .edid import decode_edid


class DisplayDevice(C.Structure):
    _fields_ = [
        ("cb", W.DWORD),
        ("name", W.WCHAR * 32),
        ("label", W.WCHAR * 128),
        ("flags", W.DWORD),
        ("device_id", W.WCHAR * 128),
        ("key", W.WCHAR * 128),
    ]


class DevMode(C.Structure):
    # The display member of the 16-byte DEVMODEW printer/display union.
    _fields_ = [
        ("device", W.WCHAR * 32),
        ("spec", W.WORD),
        ("driver", W.WORD),
        ("size", W.WORD),
        ("extra", W.WORD),
        ("fields", W.DWORD),
        ("x", W.LONG),
        ("y", W.LONG),
        ("orientation", W.DWORD),
        ("fixed", W.DWORD),
        ("misc", C.c_short * 5),
        ("form", W.WCHAR * 32),
        ("dpi", W.WORD),
        ("bpp", W.DWORD),
        ("width", W.DWORD),
        ("height", W.DWORD),
        ("flags", W.DWORD),
        ("hz", W.DWORD),
        ("tail", W.DWORD * 8),
    ]


def edid_for(device_id):
    # EDD_GET_DEVICE_INTERFACE_NAME: \\?\DISPLAY#product#instance#{guid}.
    parts = device_id.removeprefix("\\\\?\\").split("#")
    if len(parts) < 3 or parts[0].upper() != "DISPLAY":
        return b""
    try:
        path = "SYSTEM\\CurrentControlSet\\Enum\\" + "\\".join(parts[:3]) + "\\Device Parameters"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
            return winreg.QueryValueEx(key, "EDID")[0]
    except OSError:
        return b""


class WindowsBackend:
    def __init__(self):
        self.u, self.g = C.WinDLL("user32"), C.WinDLL("gdi32")
        try:
            self.backlight = WindowsBacklight(self)
        except (OSError, AttributeError):
            self.backlight = None
        self.u.EnumDisplayDevicesW.argtypes = [
            W.LPCWSTR,
            W.DWORD,
            C.POINTER(DisplayDevice),
            W.DWORD,
        ]
        self.u.EnumDisplaySettingsW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(DevMode)]
        self.g.CreateDCW.argtypes = [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, C.c_void_p]
        self.g.CreateDCW.restype = W.HDC
        self.g.DeleteDC.argtypes = [W.HDC]
        for f in (self.g.GetDeviceGammaRamp, self.g.SetDeviceGammaRamp):
            f.argtypes, f.restype = [W.HDC, C.c_void_p], W.BOOL

    def scan(self):
        devices = []
        i = 0
        while True:
            a = DisplayDevice(cb=C.sizeof(DisplayDevice))
            if not self.u.EnumDisplayDevicesW(None, i, C.byref(a), 0):
                break
            i += 1
            if not a.flags & 1 or a.flags & 8:
                continue
            children = []
            j = 0
            while True:
                child = DisplayDevice(cb=C.sizeof(DisplayDevice))
                if not self.u.EnumDisplayDevicesW(a.name, j, C.byref(child), 1):
                    break
                j += 1
                if child.flags & 1:
                    children.append(child)
            dm = DevMode(size=C.sizeof(DevMode))
            if not self.u.EnumDisplaySettingsW(a.name, 0xFFFFFFFF, C.byref(dm)):
                continue
            for child in children or [DisplayDevice()]:
                edid = edid_for(child.device_id)
                info = decode_edid(edid)
                key = (
                    "win-"
                    + hashlib.sha256((a.name + child.device_id).encode() + edid).hexdigest()[:20]
                )
                reason = (
                    "Включите расширение экрана вместо дублирования." if len(children) > 1 else ""
                )
                devices.append(
                    Monitor(
                        key,
                        info["name"] or child.label or a.name,
                        a.name,
                        dm.width,
                        dm.height,
                        dm.hz,
                        bool(a.flags & 4),
                        info["gamma"],
                        info["white"],
                        info["primaries"],
                        not reason,
                        reason,
                    )
                )
        return devices

    @contextmanager
    def dc(self, monitor):
        if not any(m.id == monitor.id and m.adjustable for m in self.scan()):
            raise DisplayError(
                "Монитор отключён или режим дублирования не допускает отдельную настройку."
            )
        dc = self.g.CreateDCW("DISPLAY", monitor.connector, None, None)
        if not dc:
            raise DisplayError("Не удалось открыть контекст выбранного монитора.")
        try:
            yield dc
        finally:
            self.g.DeleteDC(dc)

    def read(self, monitor):
        buf = ((W.WORD * 256) * 3)()
        with self.dc(monitor) as dc:
            if not self.g.GetDeviceGammaRamp(dc, C.byref(buf)):
                raise DisplayError(
                    "Драйвер не даёт прочитать гамму. Проверьте режим SDR и настройки видеокарты."
                )
        return [list(row) for row in buf]

    def write(self, monitor, ramp):
        if any(len(c) != 256 for c in ramp):
            raise DisplayError("Недопустимый размер гамма-таблицы Windows.")
        row = W.WORD * 256
        buf = (row * 3)(*(row(*c) for c in ramp))
        with self.dc(monitor) as dc:
            if not self.g.SetDeviceGammaRamp(dc, C.byref(buf)):
                raise DisplayError(
                    "Драйвер Windows отклонил коррекцию. Попробуйте менее сильное затемнение в режиме SDR."
                )
