"""Adapters operate on exact 16-bit, per-channel video LUTs, not ICC files."""

from dataclasses import dataclass
from typing import Protocol

Ramp = list[list[int]]
D65 = (0.3127, 0.3290)
SRGB = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))


class DisplayError(Exception):
    """An actionable hardware or calibration error, safe to display to the user."""


@dataclass(frozen=True)
class Monitor:
    id: str
    name: str
    connector: str
    width: int
    height: int
    hz: float
    primary: bool
    gamma: float = 2.2
    white: tuple = D65
    primaries: tuple = SRGB
    adjustable: bool = True
    reason: str = ""


class Backend(Protocol):
    def scan(self) -> list[Monitor]: ...
    def read(self, monitor: Monitor) -> Ramp: ...
    def write(self, monitor: Monitor, ramp: Ramp) -> None: ...


def valid_ramp(ramp: Ramp) -> bool:
    return (
        isinstance(ramp, list)
        and len(ramp) == 3
        and all(
            isinstance(c, list)
            and 2 <= len(c) == len(ramp[0]) <= 65536
            and all(type(x) is int and 0 <= x <= 65535 for x in c)
            for c in ramp
        )
    )
