"""Raw backlight values are journalled alongside LUTs, never just rounded percents."""

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Backlight:
    minimum: int
    current: int
    maximum: int

    def __post_init__(self):
        if not (
            all(type(n) is int for n in (self.minimum, self.current, self.maximum))
            and 0 <= self.minimum <= self.current <= self.maximum <= 0xFFFFFFFF
            and self.minimum < self.maximum
        ):
            raise ValueError("Invalid backlight range")

    @property
    def percent(self) -> int:
        return round(100 * (self.current - self.minimum) / (self.maximum - self.minimum))

    def at(self, percent: int):
        return replace(
            self, current=round(self.minimum + (self.maximum - self.minimum) * percent / 100)
        )
