"""Decode the EDID base block. Invalid/missing data is never a measurement."""

from .base import D65, SRGB


def decode_edid(data: bytes) -> dict:
    info = {"name": "", "gamma": 2.2, "white": D65, "primaries": SRGB}
    if len(data) < 128 or data[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00" or sum(data[:128]) % 256:
        return info
    for i in range(54, 126, 18):
        if data[i : i + 5] == b"\x00\x00\x00\xfc\x00":
            info["name"] = (
                data[i + 5 : i + 18].decode("ascii", "replace").split("\n")[0].strip(" \x00")
            )
    if not info["name"]:
        vendor = int.from_bytes(data[8:10], "big")
        code = "".join(chr(64 + ((vendor >> n) & 31)) for n in (10, 5, 0))
        info["name"] = f"{code} {int.from_bytes(data[10:12], 'little'):04X}"
    if data[23] != 255 and 1.4 <= (gamma := 1 + data[23] / 100) <= 3.5:
        info["gamma"] = gamma
    low = [((data[i] >> s) & 3) for i in (25, 26) for s in (6, 4, 2, 0)]
    xy = [((data[27 + i] << 2) | low[i]) / 1024 for i in range(8)]
    colors = tuple(zip(xy[::2], xy[1::2]))
    if all(0 < x < 1 and 0 < y < 1 and x + y <= 1.001 for x, y in colors):
        info["primaries"], info["white"] = colors[:3], colors[3]
    return info
