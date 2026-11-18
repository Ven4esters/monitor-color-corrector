"""Native studio shell. The GUI never opens a display handle or starts a web server."""

from datetime import datetime

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QHeaderView,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from ..color import PROFILES
from .ui import ACCENT, art, button, glyph, heading, label, layout, panel
from .worker import StudioWorker
from .workspace import Workspace


class History(QWidget):
    undoRequested = Signal()

    def __init__(self):
        super().__init__()
        box = layout(self, gap=14)
        frame = panel()
        content = layout(frame, margin=16, gap=10)
        row = heading("Журнал применений", "history")
        self.undo = button("Отменить последнее", "undo")
        self.undo.clicked.connect(self.undoRequested)
        row.addWidget(self.undo)
        content.addLayout(row)
        self.empty = label(
            "Изменений пока нет. После применения здесь появятся профиль, яркость и выбранные мониторы.",
            "secondary",
            wrap=True,
        )
        content.addWidget(self.empty)
        self.table = QTableWidget(0, 5)
        self.table.setAccessibleName("История применения профилей")
        self.table.setHorizontalHeaderLabels(
            ["Время", "Профиль", "Яркость", "Дисплеи", "Состояние"]
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(230)
        self.table.hide()
        content.addWidget(self.table)
        box.addWidget(frame)
        box.addWidget(
            label(
                "Откат возвращает все дисплеи последнего применения, а не только текущий выбор.",
                "secondary",
                wrap=True,
            )
        )
        box.addStretch()

    def set_state(self, state):
        rows = state["history"]
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))
        self.table.setRowCount(len(rows))
        names = {
            "applied": "Применено",
            "undone": "Отменено",
            "pending": "Прервано",
            "needs_restore": "Нужен откат",
            "aborted": "Без изменений",
        }
        for i, r in enumerate(rows):
            when = datetime.fromisoformat(r["time"]).astimezone().strftime("%d.%m.%Y %H:%M")
            values = [
                when,
                PROFILES[r["profile"]]["name"],
                f"{r['brightness']} %",
                ", ".join(r["names"]),
                names[r["status"]],
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(i, col, item)
        self.table.resizeRowsToContents()


class Window(QMainWindow):
    requested = Signal(str, object)
    operationFinished = Signal(str, bool)

    def __init__(self, studio_factory):
        super().__init__()
        self.setWindowTitle("Spectra Studio — настройка мониторов")
        self.setMinimumSize(565, 420)
        self.state = None
        self.busy = False
        self.closing = False
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = layout(root, gap=0)
        head = QFrame()
        head.setObjectName("header")
        bar = layout(head, row=True, gap=10)
        bar.setContentsMargins(20, 10, 20, 10)
        logo = label()
        logo.setPixmap(art("brand.svg", 30, 30))
        bar.addWidget(logo)
        bar.addWidget(label("Spectra", "brand"))
        self.brand_tag = label("STUDIO", "badge")
        bar.addWidget(self.brand_tag, 0, Qt.AlignmentFlag.AlignVCenter)
        bar.addSpacing(12)
        self.nav = QButtonGroup(self)
        self.tabs = []
        for i, (text, symbol) in enumerate([("Калибровка", "sliders"), ("История", "history")]):
            tab = button(text, symbol, "nav")
            tab.setCheckable(True)
            self.nav.addButton(tab, i)
            self.tabs.append(tab)
            bar.addWidget(tab)
        self.tabs[0].setChecked(True)
        bar.addStretch()
        self.mode = button("Подключение", role="mode", tip="Режим подключения")
        self.mode.clicked.connect(self.mode_info)
        bar.addWidget(self.mode)
        help_button = button("", "help", tip="Справка (F1)")
        help_button.setAccessibleName("Справка")
        help_button.clicked.connect(self.help)
        bar.addWidget(help_button)
        shell.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        page = QWidget()
        page.setObjectName("page")
        body = layout(page, margin=20, gap=11)
        intro = layout(row=True, gap=8)
        titles = layout(gap=1)
        titles.addWidget(label("РАБОЧАЯ ОБЛАСТЬ   /   DISPLAY LAB", "kicker"))
        self.title = label("Калибровка мониторов", "title", wrap=True)
        self.sub = label("Единый цвет и яркость для ваших дисплеев.", "secondary", wrap=True)
        titles.addWidget(self.title)
        titles.addWidget(self.sub)
        intro.addLayout(titles, 1)
        self.scan = button(
            "Обновить устройства", "refresh", tip="Повторное обнаружение дисплеев (Ctrl+R)"
        )
        self.scan.clicked.connect(lambda: self.send("scan", {}))
        intro.addWidget(self.scan)
        body.addLayout(intro)
        self.alert = label("", "warning", wrap=True)
        self.alert.hide()
        body.addWidget(self.alert)
        # A stacked layout sizes itself to *all* pages. In a scroll area that
        # leaves an empty history as tall/wide as the hidden calibration form.
        self.pages = QWidget()
        pages_box = layout(self.pages, gap=0)
        self.workspace = Workspace()
        self.history = History()
        pages_box.addWidget(self.workspace)
        pages_box.addWidget(self.history)
        self.history.hide()
        body.addWidget(self.pages, 1)
        self.nav.idClicked.connect(self.switch_page)
        self.scroll.setWidget(page)
        shell.addWidget(self.scroll, 1)
        footer = QFrame()
        footer.setObjectName("footer")
        bottom = layout(footer, row=True, gap=8)
        bottom.setContentsMargins(18, 6, 18, 6)
        bottom.addWidget(glyph("info", ACCENT, 14))
        self.status = label("Запуск студии…", "secondary", wrap=True)
        self.status.setAccessibleName("Состояние операции")
        bottom.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedSize(QSize(80, 4))
        bottom.addWidget(self.progress)
        bottom.addWidget(label("SPECTRA  /  DESKTOP", "kicker"))
        shell.addWidget(footer)
        self.workspace.applyRequested.connect(self.apply)
        self.workspace.undoRequested.connect(self.undo)
        self.history.undoRequested.connect(self.undo)
        self.shortcuts = []
        for key, fn in [
            ("F1", self.help),
            ("Ctrl+R", lambda: self.send("scan", {})),
            ("Ctrl+1", lambda: self.switch_page(0)),
            ("Ctrl+2", lambda: self.switch_page(1)),
        ]:
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(fn)
            self.shortcuts.append(sc)
        self.thread = QThread(self)
        self.worker = StudioWorker(studio_factory)
        self.worker.moveToThread(self.thread)
        self.requested.connect(self.worker.perform, Qt.ConnectionType.QueuedConnection)
        self.worker.completed.connect(self.complete)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.start()
        area = self.screen().availableGeometry()
        self.resize(min(1280, area.width() - 24), min(840, area.height() - 48))
        self.send("scan", {})

    def switch_page(self, i):
        self.tabs[i].setChecked(True)
        self.workspace.setVisible(i == 0)
        self.history.setVisible(i == 1)
        self.title.setText("Калибровка мониторов" if i == 0 else "История изменений")
        self.sub.setText(
            "Единый цвет и яркость для ваших дисплеев."
            if i == 0
            else "Сохранённые состояния и результаты применения профилей."
        )
        self.scroll.verticalScrollBar().setValue(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "workspace"):
            self.workspace.fit_width(self.width())
            self.brand_tag.setVisible(self.width() >= 730)
            self.scan.setText("Обновить устройства" if self.width() > 760 else "Обновить")

    def availability(self):
        self.workspace.set_busy(self.busy)
        self.progress.setVisible(self.busy)
        self.scan.setEnabled(not self.busy)
        self.mode.setEnabled(bool(self.state))
        self.history.undo.setEnabled(not self.busy and bool(self.state and self.state["undoId"]))

    def send(self, action, payload):
        if self.busy or self.closing:
            return
        self.busy = True
        self.availability()
        self.status.setText(
            {
                "scan": "Поиск мониторов и чтение параметров…",
                "apply": "Сохранение исходных значений и применение…",
                "undo": "Восстановление предыдущих значений…",
            }[action]
        )
        self.requested.emit(action, payload)

    @Slot(str, object, str)
    def complete(self, action, data, error):
        if data is not None:
            self.state = data
            self.workspace.set_state(data, action, not error)
            self.history.set_state(data)
            self.mode.setText("Демо-режим" if data["demo"] else "Локально")
            self.mode.setToolTip(data["notice"] or "Подключение к локальным видеовыходам")
        self.busy = False
        self.availability()
        recovery = bool(self.state and self.state["recovery"])
        text = error or (
            "Применение прервано. Подключите прежние дисплеи и выполните откат." if recovery else ""
        )
        self.alert.setText(text)
        self.alert.setVisible(bool(text))
        if error:
            self.status.setText("Операция не завершена. Подробности указаны выше.")
        elif action == "scan":
            self.status.setText(
                f"Найдено дисплеев: {len(data['monitors'])}."
                + (
                    " Демо: физические настройки не меняются."
                    if data["demo"]
                    else " Данные устройств обновлены."
                )
            )
        elif action == "apply":
            self.status.setText("Настройки применены. Исходные значения сохранены для отката.")
        else:
            self.status.setText("Сохранённые значения последней операции восстановлены.")
        self.operationFinished.emit(action, not error)
        if self.closing:
            QTimer.singleShot(0, self.close)

    def confirm(self, title, details, accept):
        box = QMessageBox(self)
        box.setWindowTitle("Spectra Studio")
        box.setIcon(QMessageBox.Icon.Question)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(title)
        box.setInformativeText(details)
        yes = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        cancel = box.addButton("Не менять", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() == yes

    def apply(self, payload):
        if self.busy or not self.state or not self.workspace.apply.isEnabled():
            return
        names = ", ".join(m["name"] for m in self.workspace.selected)
        p = PROFILES[payload["profile"]]
        if not self.state["demo"] and not self.confirm(
            "Применить коррекцию к мониторам?",
            f"{names}\n{p['name']} · {p['kelvin']} K · яркость {payload['brightness']} %\n\nИзменится изображение на выбранных выходах. Исходные значения сохранятся до записи.",
            "Применить",
        ):
            return
        self.workspace.remember_before(payload)
        self.send("apply", payload)

    def undo(self):
        if self.busy or not self.state or not (key := self.state["undoId"]):
            return
        entry = next(e for e in self.state["history"] if e["id"] == key)
        if not self.state["demo"] and not self.confirm(
            "Вернуть сохранённое состояние?",
            "Будут восстановлены все дисплеи последнего применения:\n"
            + ", ".join(entry["names"])
            + "\n\nТекущий выбор дисплея не меняет состав отката.",
            "Восстановить",
        ):
            return
        self.send("undo", {"id": key})

    def message(self, title, text):
        box = QMessageBox(self)
        box.setWindowTitle("Spectra Studio")
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(title)
        box.setInformativeText(text)
        box.addButton("Понятно", QMessageBox.ButtonRole.AcceptRole)
        box.exec()

    def mode_info(self):
        if self.state:
            self.message(
                self.mode.text(),
                (self.state["notice"] + "\n\n" if self.state["notice"] else "")
                + (
                    "В этой сессии используются виртуальные мониторы. Проверьте интерфейс и откат без изменений на компьютере."
                    if self.state["demo"]
                    else "Работаем с видеовыходами этого компьютера. Подсветка используется при поддержке DDC/CI; иначе — коррекция видеосигнала."
                ),
            )

    def help(self):
        self.message(
            "Как настроить мониторы",
            "1. Выберите все дисплеи или один выход.\n2. Выберите профиль и яркость. Сравните результат, передвигая разделитель мышью или стрелками.\n3. Примените настройки. Последнюю операцию можно отменить даже после перезапуска.\n\nБез колориметра это визуальное приближение, а не измерение яркости в нитах или точное ICC-профилирование.\n\nCtrl+R — обновить устройства. Ctrl+1 / Ctrl+2 — калибровка / история. Tab — перейти к следующему элементу.",
        )

    def stop_worker(self):
        self.thread.quit()
        self.thread.wait()

    def closeEvent(self, event):
        if self.busy:
            self.closing = True
            self.status.setText("Дождитесь завершения операции. Затем окно закроется.")
            event.ignore()
            return
        self.stop_worker()
        event.accept()
