"""Transactional calibration service shared by the local web UI and tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .backends import native_backend
from .backends.backlight import Backlight
from .backends.base import DisplayError, valid_ramp
from .backends.demo import DemoBackend
from .color import PROFILES, brightness, level, make_ramp, preview_curve, recommend


def state_dir():
    if os.getenv("SPECTRA_STATE_DIR"):
        return Path(os.environ["SPECTRA_STATE_DIR"])
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA", Path.home())) / "SpectraStudio"
    return Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state")) / "spectra-studio"


def now():
    return datetime.now(UTC).isoformat(timespec="seconds")


class Studio:
    def __init__(self, *, demo=False, directory=None, factory=native_backend):
        self.lock = threading.RLock()
        self.directory = Path(directory) if directory else state_dir()
        self.forced_demo, self.factory = demo, factory
        self.demo, self.backend, self.entries = False, None, []
        self.notice = ""
        self.monitors, self.ramps, self.lights = {}, {}, {}
        self.refresh()

    @property
    def file(self):
        return self.directory / ("demo.json" if self.demo else "displays.json")

    def load(self):
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            if data["version"] != 1 or not isinstance(data["entries"], list):
                raise ValueError("version")
            for entry in data["entries"]:
                ids = entry["ids"]
                if not (
                    isinstance(ids, list)
                    and ids
                    and all(isinstance(i, str) for i in ids)
                    and len(set(ids)) == len(ids)
                    and set(entry["before"]) == set(ids)
                    and all(valid_ramp(entry["before"][i]) for i in ids)
                    and isinstance(entry["id"], str)
                    and entry["profile"] in PROFILES
                    and type(entry["brightness"]) is int
                    and 0 <= entry["brightness"] <= 100
                    and entry["status"]
                    in ("applied", "pending", "needs_restore", "aborted", "undone")
                    and len(entry["names"]) == len(ids)
                    and all(isinstance(n, str) for n in entry["names"])
                ):
                    raise ValueError("Invalid snapshot")
                for key, raw in entry.get("backlights", {}).items():
                    if key not in ids:
                        raise ValueError("Unexpected backlight target")
                    Backlight(**raw)
                datetime.fromisoformat(entry["time"])
            self.entries = data["entries"]
            if self.demo:
                for m in self.backend.scan():
                    table = data.get("virtual", {}).get(m.id)
                    if valid_ramp(table):
                        self.backend.write(m, table)
        except FileNotFoundError:
            self.entries = []
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
            raise DisplayError(
                f"Не удалось прочитать журнал {self.file}. Сохраните его копию перед восстановлением."
            ) from exc

    def persist(self):
        data = {"version": 1, "entries": self.entries}
        if self.demo:
            data["virtual"] = self.backend.ramps
        tmp = None
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "w", dir=self.directory, encoding="utf-8", delete=False
            ) as f:
                tmp = Path(f.name)
                json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.file)
        except OSError as exc:
            raise DisplayError(
                "Не удалось сохранить резервную копию. Проверьте права и свободное место."
            ) from exc
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    def refresh(self):
        """Never silently switch an established hardware session to virtual outputs."""
        with self.lock:
            probe = self.backend is None or (self.demo and not self.forced_demo)
            if probe:
                adapter, devices = None, []
                if not self.forced_demo:
                    try:
                        adapter = self.factory()
                        devices = adapter.scan()
                    except (OSError, ImportError, AttributeError, DisplayError) as exc:
                        self.notice = (
                            str(exc)
                            if isinstance(exc, DisplayError)
                            else "Системный интерфейс управления дисплеями недоступен."
                        )
                if adapter and devices:
                    previous = self.backend, self.demo, self.notice, self.entries
                    self.backend, self.demo, self.notice = adapter, False, ""
                    try:
                        self.load()
                    except DisplayError:
                        # A failed hotplug must not pair a virtual journal with real hardware.
                        self.backend, self.demo, self.notice, self.entries = previous
                        raise
                elif not self.backend:
                    self.backend, self.demo = DemoBackend(), True
                    self.notice = (
                        self.notice
                        or "Демонстрационные дисплеи не изменяют настройки вашего компьютера."
                    )
                    self.load()
            devices = self.backend.scan()
            self.monitors, self.ramps, self.lights = {}, {}, {}
            for m in sorted(devices, key=lambda d: (not d.primary, d.connector)):
                if m.adjustable:
                    try:
                        ramp = self.backend.read(m)
                        if not valid_ramp(ramp):
                            raise DisplayError(
                                "Некорректная исходная гамма-таблица. Изменения заблокированы."
                            )
                        control = getattr(self.backend, "backlight", None)
                        if control and (light := control.read(m)) is not None:
                            self.lights[m.id] = light
                        self.ramps[m.id] = ramp
                    except (OSError, DisplayError) as exc:
                        m = replace(m, adjustable=False, reason=str(exc))
                self.monitors[m.id] = m

    def latest(self):
        return next(
            (
                r
                for r in reversed(self.entries)
                if r["status"] in ("applied", "pending", "needs_restore")
            ),
            None,
        )

    def reference_level(self, m, ramp):
        # Re-selecting a warm/dim preset must not repeatedly reduce brightness.
        # Reuse the original level only while our last correction is still active.
        for e in reversed(self.entries):
            if e["status"] != "applied" or m.id not in e["ids"]:
                continue
            light = self.lights.get(m.id)
            if (m.id in e.get("backlights", {})) != bool(light):
                break
            if light and light.current != light.at(e["brightness"]).current:
                break
            expected = make_ramp(m, e["profile"], 100 if light else e["brightness"], len(ramp[0]))
            if all(abs(a - b) <= 257 for c, d in zip(ramp, expected) for a, b in zip(c, d)):
                return e.get("reference", {}).get(m.id, brightness(e["before"][m.id]))
            break
        return self.lights[m.id].percent if m.id in self.lights else brightness(ramp)

    def state(self):
        with self.lock:
            devices, rec, levels = [], {}, []
            for m in self.monitors.values():
                ramp = self.ramps.get(m.id)
                light = self.lights.get(m.id)
                value = light.percent if light else (brightness(ramp) if ramp else None)
                reference_percent = 100 if light else 70
                identity = [[i * 257 for i in range(256)]] * 3
                curves = {
                    p: preview_curve(m, make_ramp(m, p, 100, 256), reference_percent)
                    for p in PROFILES
                }
                before = preview_curve(m, ramp or identity, reference_percent)
                if light:
                    # Approximate backlight response in linear light, not encoded RGB.
                    scale = (level(value) / level(70)) ** (1 / 2.2)
                    before = [[round(x * scale, 5) for x in channel] for channel in before]
                devices.append(
                    {
                        "id": m.id,
                        "name": m.name,
                        "connector": m.connector,
                        "width": m.width,
                        "height": m.height,
                        "hz": round(m.hz, 1),
                        "primary": m.primary,
                        "adjustable": m.adjustable,
                        "reason": m.reason,
                        "brightness": value,
                        "nativeGamma": round(m.gamma, 2),
                        "brightnessMode": "backlight" if light else "signal",
                        "previewPower": (1 if light else m.gamma) / 2.2,
                        "previewBase": level(70) if light else 1,
                        "before": before,
                        "curves": curves,
                    }
                )
                reference = [self.reference_level(m, ramp)] if ramp else []
                levels.extend(reference)
                rec[m.id] = {p: recommend(reference, p) for p in PROFILES}
            rec["all"] = {p: recommend(levels, p) for p in PROFILES}
            latest = self.latest()
            history = [
                {k: v for k, v in e.items() if k not in ("before", "reference", "backlights")}
                for e in reversed(self.entries)
            ]
            return {
                "demo": self.demo,
                "notice": self.notice,
                "monitors": devices,
                "profiles": PROFILES,
                "recommendations": rec,
                "history": history,
                "undoId": latest["id"] if latest else None,
                "recovery": bool(latest and latest["status"] != "applied"),
            }

    def write_checked(self, m, table):
        self.backend.write(m, table)
        actual = self.backend.read(m)
        # Some hardware rounds 16-bit entries to 8 or 10 bits on readback.
        if (
            not valid_ramp(actual)
            or len(actual[0]) != len(table[0])
            or any(abs(a - b) > 257 for c, d in zip(actual, table) for a, b in zip(c, d))
        ):
            raise DisplayError(
                f"{m.name}: драйвер не подтвердил запись гамма-таблицы. Проверьте HDR и ночной режим."
            )
        self.ramps[m.id] = actual

    def write_backlight(self, m, target):
        control = getattr(self.backend, "backlight", None)
        current = control.read(m) if control else None
        if not current or (current.minimum, current.maximum) != (target.minimum, target.maximum):
            raise DisplayError(
                f"{m.name}: нет доступа к прежнему диапазону подсветки. Проверьте DDC/CI."
            )
        if current != target:
            control.write(m, target)
            if control.read(m) != target:
                raise DisplayError(f"{m.name}: новое значение подсветки не подтверждено монитором.")
        self.lights[m.id] = target

    def restore_one(self, entry, i):
        # A backlight failure must not prevent LUT recovery, or vice versa.
        errors = []
        try:
            self.write_checked(self.monitors[i], entry["before"][i])
        except (OSError, DisplayError) as exc:
            errors.append(str(exc))
        if i in entry.get("backlights", {}):
            try:
                self.write_backlight(self.monitors[i], Backlight(**entry["backlights"][i]))
            except (OSError, DisplayError) as exc:
                errors.append(str(exc))
        if errors:
            raise DisplayError(" ".join(errors))

    def apply(self, ids, profile, value):
        with self.lock:
            if (
                not isinstance(profile, str)
                or profile not in PROFILES
                or type(value) is not int
                or not 0 <= value <= 100
            ):
                raise DisplayError("Выберите существующий профиль и целую яркость от 0 до 100 %.")
            if (
                not isinstance(ids, list)
                or not ids
                or not all(isinstance(i, str) for i in ids)
                or len(set(ids)) != len(ids)
            ):
                raise DisplayError("Необходимо явно выбрать мониторы для применения.")
            self.refresh()
            if any(i not in self.ramps for i in ids):
                raise DisplayError(
                    "Выбранный монитор недоступен. Обновите список и проверьте режим SDR."
                )
            latest = self.latest()
            if latest and latest["status"] != "applied":
                raise DisplayError("Сначала завершите откат прерванной операции.")
            before = {i: self.ramps[i] for i in ids}
            entry = {
                "id": uuid4().hex,
                "time": now(),
                "ids": ids,
                "names": [self.monitors[i].name for i in ids],
                "profile": profile,
                "brightness": value,
                "before": before,
                "backlights": {i: asdict(self.lights[i]) for i in ids if i in self.lights},
                "status": "pending",
                "reference": {i: self.reference_level(self.monitors[i], before[i]) for i in ids},
            }
            previous = self.entries
            self.entries = self.entries[-29:] + [entry]
            try:
                self.persist()  # Write-ahead journal, before *any* physical write.
            except Exception:
                self.entries = previous
                raise
            touched = []
            try:
                for i in ids:
                    m = self.monitors[i]
                    light = self.lights.get(i)
                    target = make_ramp(m, profile, 100 if light else value, len(before[i][0]))
                    touched.append(i)
                    self.write_checked(m, target)
                    if light:
                        self.write_backlight(m, light.at(value))
                entry["status"] = "applied"
                self.persist()
            except Exception as exc:
                failed = []
                for i in reversed(touched):
                    try:
                        self.restore_one(entry, i)
                    except (OSError, DisplayError):
                        failed.append(i)
                entry["status"] = "needs_restore" if failed else "aborted"
                self.persist()
                detail = (
                    "Подключите дисплеи и повторите откат."
                    if failed
                    else "Исходные значения восстановлены."
                )
                raise DisplayError(f"{exc} {detail}") from exc
            return self.state()

    def undo(self, expected_id):
        with self.lock:
            self.refresh()
            entry = self.latest()
            if not entry or expected_id != entry["id"]:
                raise DisplayError("История изменилась. Обновите рабочую область перед откатом.")
            for i, table in entry["before"].items():
                if (
                    i not in self.ramps
                    or not valid_ramp(table)
                    or len(table[0]) != len(self.ramps[i][0])
                ):
                    raise DisplayError(
                        "Для отката подключите те же мониторы в исходном видеорежиме."
                    )
            for i, raw in entry.get("backlights", {}).items():
                live = self.lights.get(i)
                if not live or live.minimum != raw["minimum"] or live.maximum != raw["maximum"]:
                    raise DisplayError("Для отката включите DDC/CI и подключите прежние мониторы.")
            entry["status"] = "needs_restore"
            self.persist()
            errors = []
            for i in entry["before"]:
                try:
                    self.restore_one(entry, i)
                except DisplayError as exc:
                    errors.append(str(exc))
            if errors:
                raise DisplayError("Откат не завершён. " + " ".join(errors))
            entry["status"], entry["undoneAt"] = "undone", now()
            self.persist()
            return self.state()
