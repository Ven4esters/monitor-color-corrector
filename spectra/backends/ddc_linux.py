"""Optional DDC/CI VCP 0x10 via ddcutil. Never guess a display number."""

import hashlib
import os
import re
import shutil
import subprocess
from pathlib import Path

from .backlight import Backlight
from .base import DisplayError


class LinuxBacklight:
    def __init__(self):
        self.command = shutil.which("ddcutil")
        self.drm = Path("/sys/class/drm")

    def bus(self, monitor):
        if not self.command:
            return None
        # Match the EDID that RandR actually reported, not monitor order, a
        # generic model name, or the first bus. Ambiguous twins use LUT only.
        matches = []
        for path in self.drm.glob("card*-*/edid"):
            try:
                edid = path.read_bytes()[:512]
                key = hashlib.sha256(monitor.connector.encode() + edid).hexdigest()[:20]
                if len(edid) >= 128 and monitor.id == "x11-" + key:
                    matches.append(path.parent)
            except OSError:
                continue
        if len(matches) != 1:
            return None
        try:
            target = (matches[0] / "ddc").resolve(strict=True).name
        except OSError:
            return None
        m = re.fullmatch(r"i2c-(\d+)", target)
        return m.group(1) if m else None

    def run(self, bus, *args):
        return subprocess.run(
            [self.command, "--bus", bus, "--terse", *args],
            capture_output=True,
            text=True,
            errors="replace",
            env=os.environ | {"LC_ALL": "C"},
            timeout=4,
            check=False,
        )

    def read(self, monitor):
        bus = self.bus(monitor)
        if bus is None:
            return None
        try:
            result = self.run(bus, "getvcp", "10")
            match = re.search(r"^VCP\s+10\s+C\s+(\d+)\s+(\d+)\s*$", result.stdout, re.M)
            if result.returncode == 0 and match:
                return Backlight(0, int(match.group(1)), int(match.group(2)))
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass  # Absent permissions or unsupported VCP: use software brightness.
        return None

    def write(self, monitor, target):
        bus = self.bus(monitor)
        if bus is None:
            raise DisplayError(f"{monitor.name}: не удалось однозначно определить DDC/CI-шину.")
        try:
            result = self.run(bus, "setvcp", "10", str(target.current))
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DisplayError(f"{monitor.name}: нет ответа DDC/CI.") from exc
        if result.returncode:
            raise DisplayError(
                f"{monitor.name}: не удалось записать яркость подсветки через DDC/CI."
            )
