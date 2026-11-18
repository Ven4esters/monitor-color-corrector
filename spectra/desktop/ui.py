"""Small shared components. Artwork is packaged locally and scales on HiDPI screens."""

from functools import lru_cache
from importlib.resources import files
from xml.etree import ElementTree as ET

from PySide6.QtCore import QByteArray, QDir, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

ASSETS = files("spectra").joinpath("web", "assets")
ACCENT = "#c6a9fa"
MUTED = "#b5afbf"


def theme(app: QApplication):
    QDir.setSearchPaths("spectraicons", [str(files("spectra.desktop"))])
    app.setStyle("Fusion")
    palette = app.palette()
    for role, value in {
        "Window": "#121216",
        "WindowText": "#f1eef6",
        "Base": "#19191e",
        "AlternateBase": "#201f26",
        "Text": "#f1eef6",
        "Button": "#26252c",
        "ButtonText": "#f1eef6",
        "Highlight": "#a98bd9",
        "HighlightedText": "#19151e",
        "ToolTipBase": "#292631",
        "ToolTipText": "#f3edf9",
        "PlaceholderText": "#b2a9bc",
        "Link": ACCENT,
    }.items():
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(value))
    app.setPalette(palette)
    app.setStyleSheet(files("spectra.desktop").joinpath("theme.qss").read_text(encoding="utf8"))
    app.setWindowIcon(QIcon(art("brand.svg", 44, 44)))


def svg_pixmap(data: bytes, width: int, height: int) -> QPixmap:
    image = QPixmap(width * 2, height * 2)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    QSvgRenderer(QByteArray(data)).render(p)
    p.end()
    image.setDevicePixelRatio(2)
    return image


@lru_cache(maxsize=16)
def art(filename, width, height):
    data = ASSETS.joinpath(filename).read_bytes()
    # Qt SVG uses the SVG 1.1 spelling for embedded raster thumbnails.
    if filename.startswith("monitor-"):
        data = data.replace(b"<svg ", b'<svg xmlns:xlink="http://www.w3.org/1999/xlink" ', 1)
        data = data.replace(b' href="data:', b' xlink:href="data:')
    return svg_pixmap(data, width, height)


@lru_cache(maxsize=1)
def symbols():
    root = ET.fromstring(ASSETS.joinpath("icons.svg").read_bytes())
    return {
        sym.attrib["id"]: b"".join(ET.tostring(node) for node in sym)
        for sym in root.iter("{http://www.w3.org/2000/svg}symbol")
    }


@lru_cache(maxsize=80)
def icon(name, color=MUTED, size=18):
    opening = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
    return QIcon(svg_pixmap(opening.encode() + symbols()[name] + b"</svg>", size, size))


def label(text="", role="", *, wrap=False):
    w = QLabel()
    w.setTextFormat(Qt.TextFormat.PlainText)
    w.setText(text)
    w.setObjectName(role)
    w.setWordWrap(wrap)
    return w


def glyph(name, color=MUTED, size=18):
    w = QLabel()
    w.setPixmap(icon(name, color, size).pixmap(QSize(size, size), 2))
    return w


def button(text, name=None, role="", tip=""):
    w = QPushButton(text)
    w.setObjectName(role)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        w.setIcon(icon(name, "#211927" if role == "primary" else MUTED, 16))
    w.setToolTip(tip)
    w.setAutoDefault(False)
    return w


def layout(widget=None, *, row=False, margin=0, gap=8):
    box = (QHBoxLayout if row else QVBoxLayout)(widget)
    box.setContentsMargins(margin, margin, margin, margin)
    box.setSpacing(gap)
    return box


def panel():
    w = QFrame()
    w.setObjectName("panel")
    return w


def rule():
    w = QFrame()
    w.setObjectName("rule")
    w.setFixedHeight(1)
    return w


def heading(text, symbol):
    box = layout(row=True, gap=8)
    box.addWidget(glyph(symbol, ACCENT))
    box.addWidget(label(text, "section"))
    box.addStretch()
    return box


class Choice(QPushButton):
    """A whole card is one focusable, checkable button, including its labels."""

    def __init__(self, title, details, picture, *, profile=False, tag="", value=""):
        super().__init__()
        self.setObjectName("choice" if profile else "device")
        self.setCheckable(True)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(title)
        self.setAccessibleDescription(details)
        self.setToolTip(f"{title}\n{details}")
        outer = layout(self, margin=10, gap=4)
        if tag:
            top = layout(row=True, gap=4)
            top.addWidget(label(tag, "kicker"))
            top.addStretch()
            if value:
                top.addWidget(glyph("sun", size=12))
                top.addWidget(label(value, "dimSmall"))
            outer.addLayout(top)
        line = layout(row=True, gap=10)
        visual = QLabel()
        visual.setPixmap(picture)
        line.addWidget(visual)
        words = layout(gap=2)
        words.addWidget(label(title, "choiceTitle", wrap=True))
        words.addWidget(label(details, "dimSmall"))
        line.addLayout(words, 1)
        if profile:
            self.mark = label("○", "mark")
            line.addWidget(self.mark)
            self.toggled.connect(lambda on: self.mark.setText("●" if on else "○"))
        outer.addLayout(line)
        for w in self.findChildren(QWidget):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

    def sizeHint(self):
        return self.layout().sizeHint() if self.layout() else super().sizeHint()

    def minimumSizeHint(self):
        return self.layout().minimumSize() if self.layout() else super().minimumSizeHint()
