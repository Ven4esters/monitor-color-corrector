"""The calibration draft is UI state only. Only the Apply signal carries a write request."""

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QWidget,
)

from ..color import PROFILES, level
from .preview import SCENES, Comparison, reference, tinted
from .ui import ACCENT, Choice, art, button, glyph, heading, icon, label, layout, panel, rule


class Workspace(QWidget):
    applyRequested = Signal(object)
    undoRequested = Signal()

    def __init__(self):
        super().__init__()
        self.state = None
        self.busy = True
        self.profile = "standard"
        self.devices = []
        self.device_columns = 2
        self.compact = False
        self.last_preview = self.pending_preview = None
        self.columns = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.columns.setContentsMargins(0, 0, 0, 0)
        self.columns.setSpacing(16)
        self.left = QWidget()
        self.left.setMinimumWidth(0)
        self.columns.addWidget(self.left, 3)
        left = layout(self.left, gap=12)
        title = heading("Подключённые мониторы", "monitors")
        self.count = label("—", "badge")
        title.addWidget(self.count)
        left.addLayout(title)
        self.devices_grid = QGridLayout()
        self.devices_grid.setSpacing(10)
        left.addLayout(self.devices_grid)
        self.no_devices = label("Ищем активные видеовыходы…", "secondary", wrap=True)
        left.addWidget(self.no_devices)
        self._build_preview(left)
        self._build_form()
        self.redraw = QTimer(self)
        self.redraw.setSingleShot(True)
        self.redraw.setInterval(16)
        self.redraw.timeout.connect(self.paint_draft)
        self._availability()

    def _build_preview(self, left):
        frame = panel()
        box = layout(frame, margin=13, gap=9)
        title = heading("Предпросмотр", "split")
        self.compare = QCheckBox("До / после")
        self.compare.setChecked(True)
        title.addWidget(self.compare)
        box.addLayout(title)
        self.view = Comparison()
        self.view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.compare.toggled.connect(self.view.compare)
        box.addWidget(self.view, 1)
        tools = layout(row=True, gap=7)
        tools.addWidget(glyph("image", size=15))
        self.scene = QComboBox()
        self.scene.addItems(SCENES)
        self.scene.setAccessibleName("Тестовое изображение")
        self.scene.currentIndexChanged.connect(lambda: self.redraw.start())
        tools.addWidget(self.scene)
        tools.addStretch()
        self.preview_id = label("—", "dimSmall")
        tools.addWidget(self.preview_id)
        self.expand = button("", "expand", tip="Развернуть предпросмотр")
        self.expand.setAccessibleName("Развернуть предпросмотр")
        self.expand.clicked.connect(self.zoom)
        tools.addWidget(self.expand)
        box.addLayout(tools)
        left.addWidget(frame, 1)
        metrics = panel()
        row = layout(metrics, margin=13, row=True, gap=12)
        self.metrics = []
        for title, symbol in [
            ("Белая точка", "thermometer"),
            ("Гамма", "curve"),
            ("Ориентир", "palette"),
        ]:
            slot = layout(gap=3)
            top = layout(row=True, gap=5)
            top.addWidget(glyph(symbol, size=13))
            top.addWidget(label(title, "dimSmall"))
            top.addStretch()
            val = label("—", "metric")
            slot.addLayout(top)
            slot.addWidget(val)
            row.addLayout(slot, 1)
            self.metrics.append(val)
        left.addWidget(metrics)

    def _build_form(self):
        self.form = panel()
        box = layout(self.form, margin=16, gap=9)
        self.columns.addWidget(self.form, 2)
        box.addLayout(heading("Параметры коррекции", "sliders"))
        box.addWidget(rule())
        self.scope = QComboBox()
        self.scope.setAccessibleName("Применить к мониторам")
        self.scope.setPlaceholderText("Выберите дисплей")
        self.scope.setMinimumContentsLength(15)
        self.scope.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        scope_label = label("Применить к", "field")
        scope_label.setBuddy(self.scope)
        box.addWidget(scope_label)
        box.addWidget(self.scope)
        self.scope.currentIndexChanged.connect(self.target_changed)
        row = layout(row=True)
        row.addWidget(label("Целевой профиль", "field"))
        row.addStretch()
        self.auto = button(
            "Автоподбор", "sparkles", "textAction", "Нейтральный профиль и рекомендованная яркость"
        )
        row.addWidget(self.auto)
        box.addLayout(row)
        self.auto.clicked.connect(lambda: self.choose_profile("standard"))
        self.profiles = {}
        self.group = QButtonGroup(self)
        for (key, p), color in zip(PROFILES.items(), [ACCENT, "#efba95", "#a1cbd4"]):
            choice = Choice(
                p["name"],
                f"{p['kelvin']} K   ·   Гамма {p['gamma']:.1f}",
                icon(p["icon"], color, 27).pixmap(QSize(27, 27), 2),
                profile=True,
            )
            choice.setToolTip(p["description"])
            self.group.addButton(choice)
            self.profiles[key] = choice
            choice.clicked.connect(lambda checked=False, k=key: self.choose_profile(k))
            box.addWidget(choice)
        self.profiles[self.profile].setChecked(True)
        box.addWidget(rule())
        top = layout(row=True, gap=6)
        top.addWidget(glyph("sun", size=16))
        self.brightness = QSlider(Qt.Orientation.Horizontal)
        self.brightness.setObjectName("brightness")
        self.brightness.setRange(0, 100)
        self.brightness.setAccessibleName("Яркость выбранных мониторов")
        self.brightness.setPageStep(10)
        self.number = QSpinBox()
        self.number.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.number.setToolTip("Введите значение от 0 до 100 или используйте стрелки ↑ и ↓")
        self.number.setRange(0, 100)
        self.number.setSuffix(" %")
        self.number.setKeyboardTracking(False)
        self.number.setAccessibleName("Яркость в процентах")
        b_label = label("Яркость", "field")
        b_label.setBuddy(self.number)
        top.addWidget(b_label)
        top.addStretch()
        top.addWidget(self.number)
        box.addLayout(top)
        box.addWidget(self.brightness)
        self.brightness.valueChanged.connect(self.number.setValue)
        self.number.valueChanged.connect(self.brightness.setValue)
        self.brightness.valueChanged.connect(lambda: self.redraw.start())
        hints = layout(row=True)
        self.suggest = button(
            "Рекомендация: —", role="textAction", tip="Вернуть только расчётный уровень яркости"
        )
        self.suggest.clicked.connect(self.reset_level)
        hints.addWidget(self.suggest)
        hints.addStretch()
        self.method = label("", "dimSmall")
        hints.addWidget(self.method)
        box.addLayout(hints)
        box.addStretch()
        box.addWidget(rule())
        self.apply = button("Применить настройки", "check", "primary")
        self.apply.clicked.connect(self.propose)
        box.addWidget(self.apply)
        self.undo = button(
            "Отменить применение", "undo", tip="Восстановить все мониторы последней операции"
        )
        self.undo.clicked.connect(self.undoRequested)
        box.addWidget(self.undo)
        self.hint = label("Изменения пока только в предпросмотре.", "dimSmall", wrap=True)
        box.addWidget(self.hint)

    def fit_width(self, width):
        # Stack cards too, not just the two main panels. In larger system fonts,
        # model names, percentages and modes cannot share a narrow half-width card.
        columns = 1 if width < 720 else 2
        if columns != self.device_columns:
            self.device_columns = columns
            for i, card in enumerate(self.devices):
                self.devices_grid.removeWidget(card)
                self.devices_grid.addWidget(card, i // columns, i % columns)
        narrow = width < 980
        if self.compact == narrow:
            return
        self.compact = narrow
        self.columns.setDirection(
            QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight
        )
        self.columns.setStretch(0, 0 if narrow else 3)
        self.columns.setStretch(1, 0 if narrow else 2)

    @property
    def selected(self):
        scope = self.scope.currentData()
        return [
            m for m in (self.state or {}).get("monitors", []) if scope == "all" or m["id"] == scope
        ]

    def set_state(self, data, action, success=True):
        previous = self.state
        old_scope = self.scope.currentData()
        self.state = data
        monitors = data["monitors"]
        ids = [m["id"] for m in monitors]
        if previous is None:
            target = "all" if len(ids) > 1 else next(iter(ids), None)
        elif previous["demo"] != data["demo"] or (
            old_scope == "all" and set(ids) != {m["id"] for m in previous["monitors"]}
        ):
            target = None  # Never silently widen a target after hotplug or a mode change.
        else:
            target = old_scope if old_scope in ["all", *ids] else None
        with QSignalBlocker(self.scope):
            self.scope.clear()
            if len(ids) > 1:
                self.scope.addItem(icon("monitors"), "Все мониторы  ·  " + str(len(ids)), "all")
            for i, m in enumerate(monitors, 1):
                self.scope.addItem(icon("monitor"), f"{i:02d}  ·  {m['name']}", m["id"])
            self.scope.setCurrentIndex(self.scope.findData(target) if target else -1)
        self.last_preview = self.pending_preview if success and action == "apply" else None
        self.pending_preview = None
        for w in self.devices:
            self.devices_grid.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.devices.clear()
        for i, m in enumerate(monitors):
            details = (
                f"{m['width']} × {m['height']}   ·   {m['hz']:g} Гц"
                if m["hz"]
                else f"{m['width']} × {m['height']}"
            )
            level_text = f"{m['brightness']} %" if m["brightness"] is not None else "только чтение"
            kind = "ОСНОВНОЙ" if m["primary"] else "ВНЕШНИЙ"
            card = Choice(
                m["name"],
                details,
                art(f"monitor-{'aqua' if i % 2 else 'violet'}.svg", 80, 56),
                tag=f"ДИСПЛЕЙ {i + 1:02d}   /   {kind}",
                value=level_text,
            )
            card.setToolTip(
                f"{m['name']} · {m['connector']} · {level_text}\n{m['reason'] or 'Настроить только этот дисплей'}"
            )
            card.setAccessibleDescription(f"{details}; яркость: {level_text}")
            card.clicked.connect(lambda _, key=m["id"]: self.pick_device(key))
            self.devices_grid.addWidget(card, i // self.device_columns, i % self.device_columns)
            self.devices.append(card)
        self.count.setText(f"{len(ids):02d}")
        self.no_devices.setVisible(not ids)
        self.no_devices.setText("Нет активных дисплеев. Подключите монитор и обновите список.")
        self._sync_draft(reset_level=previous is None or target != old_scope or action == "undo")

    def pick_device(self, key):
        idx = self.scope.findData(key)
        if idx == self.scope.currentIndex():
            self._sync_draft(False)
        else:
            self.scope.setCurrentIndex(idx)

    def target_changed(self):
        if self.state:
            self._sync_draft(True)

    def choose_profile(self, key):
        self.profile = key
        self.profiles[key].setChecked(True)
        self._sync_draft(True)

    def recommended(self):
        return (
            (self.state or {})
            .get("recommendations", {})
            .get(self.scope.currentData(), {})
            .get(self.profile)
        )

    def reset_level(self):
        if (v := self.recommended()) is not None:
            self.brightness.setValue(v)

    def _sync_draft(self, reset_level):
        if reset_level:
            self.reset_level()
        selected = self.selected
        for i, card in enumerate(self.devices):
            card.setChecked(self.state["monitors"][i] in selected)
        p = PROFILES[self.profile]
        for w, text in zip(self.metrics, (f"{p['kelvin']} K", f"{p['gamma']:.1f}", p["space"])):
            w.setText(text)
        self.suggest.setText(
            f"Рекомендация: {self.recommended()} %" if selected else "Рекомендация: —"
        )
        modes = {m["brightnessMode"] for m in selected}
        self.method.setText(
            "Смешанный режим"
            if len(modes) > 1
            else ("Подсветка" if "backlight" in modes else "Видеосигнал" if modes else "")
        )
        self.preview_id.setText(
            f"Дисплей {self.state['monitors'].index(selected[0]) + 1:02d}"
            if selected
            else "Нет цели"
        )
        self.redraw.start()
        self._availability()

    def paint_draft(self):
        current = self.selected
        scene = self.scene.currentText()
        if not current:
            self.view.images(reference(scene), reference(scene))
            return
        m = current[0]
        amount = self.brightness.value()
        old = self.last_preview or {}
        before = (
            old.get("curves", {}).get(m["id"], m["before"])
            if (old.get("profile"), old.get("brightness")) == (self.profile, amount)
            else m["before"]
        )
        scale = (level(amount) / m["previewBase"]) ** m["previewPower"]
        self.view.images(tinted(scene, before), tinted(scene, m["curves"][self.profile], scale))

    def set_busy(self, busy):
        self.busy = busy
        self._availability()

    def _availability(self):
        targets = self.selected
        active = bool(targets) and not self.busy
        recovery = bool(self.state and self.state["recovery"])
        blocked = next((m for m in targets if not m["adjustable"]), None)
        self.scope.setEnabled(not self.busy and bool(self.state and self.state["monitors"]))
        for d in self.devices:
            d.setEnabled(not self.busy)
        for w in [*self.profiles.values(), self.brightness, self.number, self.auto, self.suggest]:
            w.setEnabled(active)
        self.apply.setEnabled(active and not recovery and not blocked)
        self.undo.setEnabled(not self.busy and bool(self.state and self.state["undoId"]))
        self.undo.setToolTip(
            "Восстановить все мониторы последнего применения"
            if self.state and self.state["undoId"]
            else "Откат будет доступен после применения"
        )
        self.hint.setText(
            "Сначала восстановите прерванную операцию."
            if recovery
            else blocked["reason"]
            if blocked
            else "Выберите дисплей для настройки."
            if not targets
            else "До применения меняется только предпросмотр."
        )
        self.expand.setEnabled(bool(targets))

    def propose(self):
        if not self.apply.isEnabled():
            return
        payload = {
            "ids": [m["id"] for m in self.selected],
            "profile": self.profile,
            "brightness": self.brightness.value(),
        }
        self.applyRequested.emit(payload)

    def remember_before(self, payload):
        self.pending_preview = {**payload, "curves": {m["id"]: m["before"] for m in self.selected}}

    def zoom(self):
        self.paint_draft()
        dlg = QDialog(self)
        dlg.setWindowTitle("Предпросмотр · Spectra Studio")
        box = layout(dlg, margin=14, gap=10)
        box.addWidget(
            label(
                f"{self.selected[0]['name']}  /  {PROFILES[self.profile]['name']}  /  {self.brightness.value()} %",
                "section",
            )
        )
        large = Comparison()
        large.images(self.view.before, self.view.after)
        large.compare(self.compare.isChecked())
        large.setValue(self.view.value())
        box.addWidget(large, 1)
        footer = layout(row=True)
        footer.addWidget(
            label("Перетащите границу или используйте стрелки ← →.", "secondary", wrap=True)
        )
        footer.addStretch()
        close = button("Закрыть")
        close.clicked.connect(dlg.accept)
        footer.addWidget(close)
        box.addLayout(footer)
        area = self.screen().availableGeometry()
        dlg.resize(min(1080, area.width() - 35), min(630, area.height() - 60))
        large.setFocus()
        dlg.exec()
        self.view.setValue(large.value())
        dlg.deleteLater()
