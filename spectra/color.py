"""Relative, EDID-based white balance. No claim of measured luminance or gamut."""

from statistics import median

from .backends.base import D65, SRGB, Monitor, Ramp

PROFILES = {
    "standard": {
        "name": "Стандарт sRGB",
        "kelvin": 6500,
        "gamma": 2.2,
        "space": "sRGB",
        "factor": 1.0,
        "white": D65,
        "icon": "aperture",
        "description": "Нейтральная белая точка для повседневной работы, фотографий и веб-графики.",
    },
    "warm": {
        "name": "Тёплый вечер",
        "kelvin": 5000,
        "gamma": 2.2,
        "space": "sRGB",
        "factor": 0.78,
        "white": (0.3457, 0.3585),
        "icon": "sunset",
        "description": "Мягкий тёплый белый и пониженная яркость для чтения при вечернем освещении.",
    },
    "cinema": {
        "name": "Кинопросмотр",
        "kelvin": 6500,
        "gamma": 2.4,
        "space": "Rec. 709",
        "factor": 0.65,
        "white": D65,
        "icon": "film",
        "description": "Нейтральный белый и более глубокие полутона для просмотра видео в тёмной комнате.",
    },
}
MIN_SIGNAL = 0.12  # Even 0% must leave the Undo control visible.


def level(percent):
    return MIN_SIGNAL + (1 - MIN_SIGNAL) * percent / 100


def brightness(ramp: Ramp) -> int:
    return round(
        max(0, min(100, 100 * (max(c[-1] for c in ramp) / 65535 - MIN_SIGNAL) / (1 - MIN_SIGNAL)))
    )


def recommend(values, profile):
    normal = min(85, max(25, median(values) if values else 70))
    return int(5 * round(normal * PROFILES[profile]["factor"] / 5))


def xyz(xy):
    x, y = xy
    return (x / y, 1.0, (1 - x - y) / y)


def det(cols):
    a, b, c = cols
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - b[0] * (a[1] * c[2] - a[2] * c[1])
        + c[0] * (a[1] * b[2] - a[2] * b[1])
    )


def white_mix(primaries, white):
    """RGB coefficients needed to make a specified XYZ white in these primaries."""
    cols = [xyz(p) for p in primaries]
    d = det(cols)
    if abs(d) < 1e-8:
        return (1.0, 1.0, 1.0)
    return [det(cols[:i] + [xyz(white)] + cols[i + 1 :]) / d for i in range(3)]


def gains(monitor, target):
    native = white_mix(monitor.primaries, monitor.white)
    desired = white_mix(monitor.primaries, target)
    lin = [max(0.05, t / max(0.01, n)) for n, t in zip(native, desired)]
    return [(v / max(lin)) ** (1 / monitor.gamma) for v in lin]


def make_ramp(monitor: Monitor, profile: str, percent: int, size: int) -> Ramp:
    p = PROFILES[profile]
    power = p["gamma"] / monitor.gamma
    return [
        [round(65535 * level(percent) * g * (i / (size - 1)) ** power) for i in range(size)]
        for g in gains(monitor, p["white"])
    ]


def preview_curve(monitor, ramp, reference_percent=70):
    """Small display-referred RGB curves for the browser's SVG preview filter."""
    # Simulate the native white on a reference sRGB display, relative to 70%.
    ref = white_mix(SRGB, D65)
    src = white_mix(SRGB, monitor.white)
    ratio = [max(0.01, n / r) for n, r in zip(src, ref)]
    tint = [(v / max(ratio)) ** (1 / 2.2) for v in ratio]
    power = monitor.gamma / 2.2
    # Use a neutral target at 70% as the visual reference. This also accounts for
    # the headroom lost when white-balance correction attenuates a channel.
    reference = max(
        (level(reference_percent) * g) ** power * t for g, t in zip(gains(monitor, D65), tint)
    )
    n = len(ramp[0]) - 1
    return [
        [
            round((ramp[c][round(i * n / 32)] / 65535) ** power * tint[c] / reference, 5)
            for i in range(33)
        ]
        for c in range(3)
    ]
