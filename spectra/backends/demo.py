from copy import deepcopy

from ..color import level
from .base import Monitor, Ramp


class DemoBackend:
    """Isolated virtual outputs; no native device calls, even when applying."""

    def __init__(self):
        self.devices = [
            Monitor(
                "demo-dell",
                "Dell U2723QE",
                "DP-1",
                3840,
                2160,
                60,
                True,
                gamma=2.05,
                white=(0.282, 0.292),
            ),
            Monitor(
                "demo-lg",
                "LG 27UL850",
                "HDMI-1",
                3840,
                2160,
                60,
                False,
                gamma=2.32,
                white=(0.335, 0.35),
            ),
        ]
        self.ramps = {
            d.id: [[round(65535 * level(p) * (i / 255) ** g) for i in range(256)] for _ in range(3)]
            for d, p, g in zip(self.devices, (46, 94), (1.02, 0.96))
        }

    def scan(self):
        return self.devices[:]

    def read(self, monitor):
        return deepcopy(self.ramps[monitor.id])

    def write(self, monitor: Monitor, ramp: Ramp):
        self.ramps[monitor.id] = deepcopy(ramp)
