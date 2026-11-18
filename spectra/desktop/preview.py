"""Read-only RGB preview: apply display-referred curves to reference pixels, not hardware."""

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSlider

from .ui import ASSETS

SCENES = ("Альпийское озеро", "Цветовая шкала", "Градации серого")


@lru_cache(maxsize=3)
def reference(scene: str) -> QImage:
    if scene == SCENES[0]:
        image = QImage.fromData(ASSETS.joinpath("alpine-lake.jpg").read_bytes())
        if image.isNull():
            raise ValueError("Не удалось открыть тестовое изображение.")
        return image.scaledToWidth(
            1000, Qt.TransformationMode.SmoothTransformation
        ).convertToFormat(QImage.Format.Format_RGBA8888)
    image = QImage(1000, 425, QImage.Format.Format_RGBA8888)
    colors = (
        ("#e6e5de", "#d7c746", "#62bfbd", "#7bbb76", "#c57bb1", "#ca675d", "#657dbe")
        if scene == SCENES[1]
        else [QColor(v, v, v) for v in range(0, 256, 17)]
    )
    p = QPainter(image)
    for i, color in enumerate(colors):
        x = i * image.width() // len(colors)
        p.fillRect(x, 0, (i + 1) * image.width() // len(colors) - x, image.height(), QColor(color))
    grad = QLinearGradient(0, 0, image.width(), 0)
    grad.setColorAt(0, QColor("black"))
    grad.setColorAt(1, QColor("white"))
    p.fillRect(0, 325, image.width(), 100, grad)
    p.end()
    return image


def lut(samples, scale):
    result = bytearray(256)
    for i in range(256):
        x = i * (len(samples) - 1) / 255
        n = int(x)
        v = samples[n] + (samples[min(n + 1, len(samples) - 1)] - samples[n]) * (x - n)
        result[i] = round(255 * min(1, max(0, v * scale)))
    return bytes(result)


@lru_cache(maxsize=8)
def _tinted(scene, tables):
    base = reference(scene)
    pixels = bytearray(base.constBits())
    for i, table in enumerate(tables):
        pixels[i::4] = pixels[i::4].translate(table)
    return QImage(pixels, base.width(), base.height(), base.bytesPerLine(), base.format()).copy()


def tinted(scene, curves, scale=1.0):
    return _tinted(scene, tuple(lut(channel, scale) for channel in curves))


class Comparison(QSlider):
    """A native slider (arrows, Home/End, accessibility) with an image as its track."""

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.setRange(0, 100)
        self.setValue(48)
        self.setAccessibleName("Разделитель до и после")
        self.setAccessibleDescription(
            "Перетащите границу или перемещайте её стрелками влево и вправо."
        )
        self.setToolTip(self.accessibleDescription())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(174)
        self.setMinimumWidth(120)
        self.before = self.after = reference(SCENES[0])
        self.compare(True)
        self.valueChanged.connect(self.update)

    def images(self, before, after):
        self.before, self.after = before, after
        self.update()

    def compare(self, enabled):
        self.split = enabled
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus if enabled else Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.SplitHCursor if enabled else Qt.CursorShape.ArrowCursor)
        self.update()

    def seek(self, event):
        self.setValue(round(event.position().x() * 100 / max(1, self.width() - 1)))
        event.accept()

    def mousePressEvent(self, event):
        if self.split and event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setSliderDown(True)
            self.seek(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            self.seek(event)

    def mouseReleaseEvent(self, event):
        if self.isSliderDown():
            self.seek(event)
            self.setSliderDown(False)

    def wheelEvent(self, event):
        event.ignore()  # scrolling the page must not move the divider

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        width, height = self.width(), self.height()
        bounds = QRectF(0, 0, width, height)
        path = QPainterPath()
        path.addRoundedRect(bounds, 8, 8)
        p.setClipPath(path)
        factor = max(width / self.after.width(), height / self.after.height())
        w, h = width / factor, height / factor
        crop = QRectF((self.after.width() - w) / 2, (self.after.height() - h) / 2, w, h)
        p.drawImage(bounds, self.after, crop)
        x = width * self.value() / 100
        if self.split:
            p.save()
            p.setClipRect(QRectF(0, 0, x, height), Qt.ClipOperation.IntersectClip)
            p.drawImage(bounds, self.before, crop)
            p.restore()
            p.setPen(QPen(QColor("#fffaff"), 2))
            p.drawLine(QPointF(x, 0), QPointF(x, height))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#f7f3fa"))
            p.drawEllipse(QPointF(x, height / 2), 16, 16)
            p.setPen(QPen(QColor("#49404e"), 1.8))
            for sign in (-1, 1):
                a, b = x + sign * 8, x + sign * 4
                p.drawLine(QPointF(b, height / 2 - 4), QPointF(a, height / 2))
                p.drawLine(QPointF(a, height / 2), QPointF(b, height / 2 + 4))
        for txt, left in [("После", False)] + ([("До", True)] if self.split else []):
            pill = QRectF(10 if left else width - 70, 10, 43 if left else 60, 25)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(29, 23, 35, 175))
            p.drawRoundedRect(pill, 5, 5)
            p.setPen(QColor("white"))
            p.drawText(pill, Qt.AlignmentFlag.AlignCenter, txt)
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#dbc3ff"), 3))
            p.drawRoundedRect(bounds.adjusted(1, 1, -1, -1), 8, 8)
        p.end()
