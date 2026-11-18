"""X11/RandR 1.3+. Use full native gamma tables so Undo is lossless."""

import ctypes as C
import hashlib
import os
from contextlib import contextmanager

from .base import DisplayError, Monitor
from .ddc_linux import LinuxBacklight
from .edid import decode_edid

UL, UI, US, Int, V, P = C.c_ulong, C.c_uint, C.c_ushort, C.c_int, C.c_void_p, C.POINTER


class Mode(C.Structure):
    _fields_ = [
        ("id", UL),
        ("width", UI),
        ("height", UI),
        ("clock", UL),
        ("hs", UI),
        ("he", UI),
        ("ht", UI),
        ("skew", UI),
        ("vs", UI),
        ("ve", UI),
        ("vt", UI),
        ("name", C.c_char_p),
        ("name_len", UI),
        ("flags", UL),
    ]


class Resources(C.Structure):
    _fields_ = [
        ("ts", UL),
        ("config_ts", UL),
        ("nc", Int),
        ("crtcs", P(UL)),
        ("no", Int),
        ("outputs", P(UL)),
        ("nm", Int),
        ("modes", P(Mode)),
    ]


class Output(C.Structure):
    _fields_ = [
        ("ts", UL),
        ("crtc", UL),
        ("name", C.c_char_p),
        ("name_len", Int),
        ("mmw", UL),
        ("mmh", UL),
        ("connection", US),
        ("subpixel", US),
        ("nc", Int),
        ("crtcs", P(UL)),
        ("nclone", Int),
        ("clones", P(UL)),
        ("nm", Int),
        ("preferred", Int),
        ("modes", P(UL)),
    ]


class Crtc(C.Structure):
    _fields_ = [
        ("ts", UL),
        ("x", Int),
        ("y", Int),
        ("width", UI),
        ("height", UI),
        ("mode", UL),
        ("rotation", US),
        ("no", Int),
        ("outputs", P(UL)),
        ("rotations", US),
        ("npossible", Int),
        ("possible", P(UL)),
    ]


class Gamma(C.Structure):
    _fields_ = [("size", Int), ("red", P(US)), ("green", P(US)), ("blue", P(US))]


def bind(lib, name, ret, *args):
    f = getattr(lib, name)
    f.restype, f.argtypes = ret, args
    return f


class LinuxBackend:
    def __init__(self):
        if os.getenv("XDG_SESSION_TYPE", "").lower() == "wayland" or os.getenv("WAYLAND_DISPLAY"):
            raise DisplayError(
                "Для управления физическими дисплеями Linux нужен сеанс X11, а не Wayland."
            )
        if not os.getenv("DISPLAY"):
            raise DisplayError("В этой среде нет графического сеанса с физическими мониторами.")
        self.backlight = LinuxBacklight()
        self.x = x = C.CDLL("libX11.so.6")
        self.r = r = C.CDLL("libXrandr.so.2")
        bind(x, "XOpenDisplay", V, C.c_char_p)
        bind(x, "XCloseDisplay", Int, V)
        bind(x, "XDefaultRootWindow", UL, V)
        bind(x, "XInternAtom", UL, V, C.c_char_p, Int)
        bind(x, "XFree", Int, V)
        bind(x, "XSync", Int, V, Int)
        bind(x, "XSetErrorHandler", V, V)
        bind(r, "XRRQueryVersion", Int, V, P(Int), P(Int))
        bind(r, "XRRGetScreenResourcesCurrent", P(Resources), V, UL)
        bind(r, "XRRFreeScreenResources", None, P(Resources))
        bind(r, "XRRGetOutputPrimary", UL, V, UL)
        bind(r, "XRRGetOutputInfo", P(Output), V, P(Resources), UL)
        bind(r, "XRRFreeOutputInfo", None, P(Output))
        bind(r, "XRRGetCrtcInfo", P(Crtc), V, P(Resources), UL)
        bind(r, "XRRFreeCrtcInfo", None, P(Crtc))
        bind(
            r,
            "XRRGetOutputProperty",
            Int,
            V,
            UL,
            UL,
            C.c_long,
            C.c_long,
            Int,
            Int,
            UL,
            P(UL),
            P(Int),
            P(UL),
            P(UL),
            P(V),
        )
        bind(r, "XRRGetCrtcGammaSize", Int, V, UL)
        bind(r, "XRRGetCrtcGamma", P(Gamma), V, UL)
        bind(r, "XRRAllocGamma", P(Gamma), Int)
        bind(r, "XRRSetCrtcGamma", None, V, UL, P(Gamma))
        bind(r, "XRRFreeGamma", None, P(Gamma))

    @contextmanager
    def connection(self):
        d = self.x.XOpenDisplay(None)
        if not d:
            raise DisplayError(
                "Нет доступа к X11. Запустите Spectra в локальном сеансе пользователя."
            )
        errors = []
        callback = C.CFUNCTYPE(Int, V, V)(lambda *_: errors.append(True) or 0)
        old = self.x.XSetErrorHandler(C.cast(callback, V))
        try:
            a, b = Int(), Int()
            if not self.r.XRRQueryVersion(d, C.byref(a), C.byref(b)) or (a.value, b.value) < (1, 3):
                raise DisplayError("Требуется расширение XRandR версии 1.3 или новее.")
            yield d
            self.x.XSync(d, 0)
            if errors:
                raise DisplayError(
                    "X11 не принял операцию. Обновите список подключённых мониторов."
                )
        finally:
            self.x.XCloseDisplay(d)
            self.x.XSetErrorHandler(old)

    def edid(self, d, output):
        atom = self.x.XInternAtom(d, b"EDID", 1)
        if not atom:
            return b""
        kind, fmt, count, extra, ptr = UL(), Int(), UL(), UL(), V()
        status = self.r.XRRGetOutputProperty(
            d,
            output,
            atom,
            0,
            128,
            0,
            0,
            0,
            C.byref(kind),
            C.byref(fmt),
            C.byref(count),
            C.byref(extra),
            C.byref(ptr),
        )
        try:
            return (
                C.string_at(ptr, min(count.value, 512))
                if not status and ptr and fmt.value == 8
                else b""
            )
        finally:
            if ptr:
                self.x.XFree(ptr)

    def outputs(self, d):
        root = self.x.XDefaultRootWindow(d)
        res = self.r.XRRGetScreenResourcesCurrent(d, root)
        if not res:
            raise DisplayError("Не удалось прочитать конфигурацию XRandR.")
        devices = {}
        try:
            s = res.contents
            primary = self.r.XRRGetOutputPrimary(d, root)
            for output_index in range(s.no):
                oid = s.outputs[output_index]
                op = self.r.XRRGetOutputInfo(d, res, oid)
                if not op:
                    continue
                try:
                    o = op.contents
                    if o.connection != 0 or not o.crtc:
                        continue
                    cp = self.r.XRRGetCrtcInfo(d, res, o.crtc)
                    if not cp:
                        continue
                    try:
                        c = cp.contents
                        conn = o.name.decode("utf-8", "replace")
                        edid = self.edid(d, oid)
                        info = decode_edid(edid)
                        key = "x11-" + hashlib.sha256(conn.encode() + edid).hexdigest()[:20]
                        hz = 0.0
                        for m in s.modes[: s.nm]:
                            if m.id == c.mode and m.ht and m.vt:
                                hz = (
                                    m.clock
                                    / (m.ht * m.vt)
                                    * (2 if m.flags & 16 else 1)
                                    / (2 if m.flags & 32 else 1)
                                )
                        reason = ""
                        if c.no > 1:
                            reason = "Для независимой настройки включите расширенный рабочий стол вместо дублирования."
                        elif self.r.XRRGetCrtcGammaSize(d, o.crtc) < 2:
                            reason = "Драйвер не предоставляет таблицу гаммы для этого выхода."
                        devices[key] = (
                            Monitor(
                                key,
                                info["name"] or conn,
                                conn,
                                c.width,
                                c.height,
                                hz,
                                oid == primary,
                                info["gamma"],
                                info["white"],
                                info["primaries"],
                                not reason,
                                reason,
                            ),
                            o.crtc,
                        )
                    finally:
                        self.r.XRRFreeCrtcInfo(cp)
                finally:
                    self.r.XRRFreeOutputInfo(op)
            return devices
        finally:
            self.r.XRRFreeScreenResources(res)

    def scan(self):
        with self.connection() as d:
            return [entry[0] for entry in self.outputs(d).values()]

    def resolve(self, d, monitor):
        entry = self.outputs(d).get(monitor.id)
        if not entry or not entry[0].adjustable:
            raise DisplayError("Монитор отключён или конфигурация выходов изменилась.")
        return entry[1]

    def read(self, monitor):
        with self.connection() as d:
            p = self.r.XRRGetCrtcGamma(d, self.resolve(d, monitor))
            if not p:
                raise DisplayError("Не удалось получить исходную гамма-таблицу.")
            try:
                g = p.contents
                if not 2 <= g.size <= 65536:
                    raise DisplayError("Драйвер вернул некорректный размер гамма-таблицы.")
                return [channel[: g.size] for channel in (g.red, g.green, g.blue)]
            finally:
                self.r.XRRFreeGamma(p)

    def write(self, monitor, ramp):
        with self.connection() as d:
            crtc = self.resolve(d, monitor)
            size = self.r.XRRGetCrtcGammaSize(d, crtc)
            if size != len(ramp[0]):
                raise DisplayError(
                    "Размер гамма-таблицы изменился. Восстановите прежний видеорежим."
                )
            p = self.r.XRRAllocGamma(size)
            if not p:
                raise DisplayError("Не удалось выделить память для гамма-таблицы.")
            try:
                for dest, src in zip((p.contents.red, p.contents.green, p.contents.blue), ramp):
                    C.memmove(dest, (US * size)(*src), size * C.sizeof(US))
                self.r.XRRSetCrtcGamma(d, crtc, p)
            finally:
                self.r.XRRFreeGamma(p)
