"""Frame display with a fixed drawing toolbar."""

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPaintEvent, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from ..hud import HudLayout


def to_pixmap(frame: np.ndarray) -> QPixmap:
    """Copy a BGR frame or grayscale mask into a pixmap."""
    frame = np.ascontiguousarray(frame)
    height, width = frame.shape[:2]
    format = QImage.Format_Grayscale8 if frame.ndim == 2 else QImage.Format_BGR888
    image = QImage(frame.data, width, height, frame.strides[0], format)
    return QPixmap.fromImage(image.copy())


class FrameView(QWidget):
    def __init__(self, hud: HudLayout | None = None) -> None:
        super().__init__()
        self.hud = hud
        self.active_index = 0
        self.pixmap = None
        self.setMinimumSize(240, 180)

    def set_frame(self, frame: np.ndarray) -> None:
        self.pixmap = to_pixmap(frame)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 27))
        if self.pixmap is None:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "No camera frame")
            return

        width, height = self.pixmap.width(), self.pixmap.height()
        scale = min(self.width() / width, self.height() / height)
        painter.translate(
            (self.width() - width * scale) / 2,
            (self.height() - height * scale) / 2,
        )
        painter.scale(scale, scale)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, self.pixmap)

        if self.hud is None:
            return
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        painter.setFont(font)
        for button, (x1, y1, x2, y2) in self.hud.rects(width, height):
            selected = button.action == "set_color" and button.arg == self.active_index
            painter.setPen(QPen(Qt.white, 3 if selected else 1))
            painter.setBrush(QColor(button.fill))
            box = QRectF(x1, y1, x2 - x1, y2 - y1)
            painter.drawRect(box)
            if button.label:
                painter.drawText(box, Qt.AlignCenter, button.label)
