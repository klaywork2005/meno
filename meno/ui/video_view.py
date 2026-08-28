"""A widget that displays a frame and paints the HUD over it.

The HUD is drawn with QPainter rather than into the pixels, so the paint canvas
stays free of the toolbar and the HUD gets antialiased text, rounded corners
and alpha.

Everything drawn comes from the same :class:`~meno.hud.HudLayout` the vision
code hit-tests against, so displayed and pressable geometry cannot diverge.

The widget also edits that layout: in edit mode, dragging a button moves it,
dragging its left or right edge resizes it, and dragging the bottom of the
strip changes the strip height. Because the layout stores fractions, dragging
in a 1280-wide window produces a layout that is still correct at 640.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QMouseEvent,
                           QPainter, QPaintEvent, QPen, QPixmap)
from PySide6.QtWidgets import QWidget

from ..hud import HudButton, HudLayout, hex_to_rgb

# Distance from an edge, in widget pixels, that counts as grabbing that edge
# rather than the button body.
EDGE_GRAB = 8

# Minimum button width, as a fraction of the frame. Prevents a button from
# being dragged too narrow to grab again.
MIN_WIDTH_PCT = 0.03

# Background colour of the widget outside the frame.
BACKDROP = QColor(24, 24, 27)


def to_pixmap(frame: np.ndarray) -> QPixmap:
    """Convert an OpenCV array to a QPixmap.

    Accepts both 3-channel BGR frames and the single-channel mask. The final
    ``.copy()`` is required: QImage wraps the numpy buffer without owning it,
    so without a copy the pixmap can outlive the array.
    """
    if frame.ndim == 2:
        frame = np.ascontiguousarray(frame)
        h, w = frame.shape
        image = QImage(frame.data, w, h, w, QImage.Format_Grayscale8)
    else:
        frame = np.ascontiguousarray(frame[:, :, ::-1])  # BGR -> RGB
        h, w, _ = frame.shape
        image = QImage(frame.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(image.copy())


def _qcolor(hex_value: str, alpha: float = 1.0) -> QColor:
    """Convert ``"#rrggbb"`` and an alpha fraction to a QColor."""
    r, g, b = hex_to_rgb(hex_value)
    color = QColor(r, g, b)
    color.setAlphaF(alpha)
    return color


class FrameView(QWidget):
    """Displays frames, optionally with the HUD on top.

    Used three times: the live feed (HUD on, editable), the paint canvas and
    the mask (HUD off).
    """

    #: Emitted after a drag finishes, so the window can persist the layout.
    layout_changed = Signal()

    def __init__(self, hud: HudLayout | None = None, show_hud: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hud = hud
        self.show_hud = show_hud
        self.edit_mode = False

        #: Index into the palette of the selected brush, so the matching
        #: button can be highlighted.
        self.active_index = 0

        self._pixmap: QPixmap | None = None
        self._frame_size = (640, 480)

        # Drag state: the kind of grab, the button, and the offset between the
        # cursor and the button's left edge at grab time.
        self._drag: tuple[str, HudButton | None, float] | None = None

        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)

    # --- Input from the app ----------------------------------------------

    def set_frame(self, frame: np.ndarray) -> None:
        """Display a new frame."""
        self._frame_size = (frame.shape[1], frame.shape[0])
        self._pixmap = to_pixmap(frame)
        self.update()

    def set_active_index(self, index: int) -> None:
        """Set which palette entry is highlighted as selected."""
        if index != self.active_index:
            self.active_index = index
            self.update()

    def set_edit_mode(self, enabled: bool) -> None:
        """Enable or disable HUD editing."""
        self.edit_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.update()

    # --- Coordinate mapping ----------------------------------------------
    # The frame is letterboxed into the widget, so widget coordinates are not
    # frame coordinates. Both conversions live here and nowhere else.

    def _target_rect(self) -> QRectF:
        """The rectangle the frame is drawn into."""
        fw, fh = self._frame_size
        if fw == 0 or fh == 0:
            return QRectF(self.rect())
        scale = min(self.width() / fw, self.height() / fh)
        w, h = fw * scale, fh * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _to_widget(self, x: float, y: float) -> QPointF:
        """Convert frame coordinates to widget coordinates."""
        rect, (fw, fh) = self._target_rect(), self._frame_size
        return QPointF(rect.x() + x * rect.width() / fw,
                       rect.y() + y * rect.height() / fh)

    def _to_frame(self, pos: QPointF) -> tuple[float, float]:
        """Convert widget coordinates to frame coordinates."""
        rect, (fw, fh) = self._target_rect(), self._frame_size
        if rect.width() == 0 or rect.height() == 0:
            return (0.0, 0.0)
        return ((pos.x() - rect.x()) * fw / rect.width(),
                (pos.y() - rect.y()) * fh / rect.height())

    # --- Painting ---------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), BACKDROP)
        if self._pixmap is None:
            painter.setPen(QColor(140, 140, 150))
            painter.drawText(self.rect(), Qt.AlignCenter, "No camera frame")
            return

        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.drawPixmap(self._target_rect(), self._pixmap,
                           QRectF(self._pixmap.rect()))

        if self.show_hud and self.hud is not None:
            painter.setRenderHint(QPainter.Antialiasing)
            self._paint_hud(painter)

    def _paint_hud(self, painter: QPainter) -> None:
        """Draw the button strip over the frame."""
        theme = self.hud.theme
        fw, fh = self._frame_size
        rect = self._target_rect()
        scale = rect.height() / fh if fh else 1.0
        radius = theme.get("corner_radius", 6) * scale

        font = QFont(self.font())
        font.setPixelSize(max(8, int(theme.get("font_px", 13) * scale)))
        font.setBold(True)
        painter.setFont(font)

        for button, (x1, y1, x2, y2) in self.hud.rects(fw, fh):
            top_left = self._to_widget(x1, y1)
            bottom_right = self._to_widget(x2, y2)
            box = QRectF(top_left, bottom_right)

            painter.setBrush(QBrush(_qcolor(button.fill,
                                            theme.get("opacity", 0.85))))

            # The selected brush gets a thicker border, so no separate
            # indicator is needed.
            selected = (button.action == "set_color"
                        and button.arg == self.active_index)
            if selected:
                pen = QPen(_qcolor(theme.get("active_border_color", "#ffffff")),
                           theme.get("active_border_width", 3))
            else:
                pen = QPen(_qcolor(theme.get("border_color", "#ffffff"), 0.6),
                           theme.get("border_width", 1))
            painter.setPen(pen)
            painter.drawRoundedRect(box, radius, radius)

            if button.label:
                painter.setPen(_qcolor(theme.get("label_color", "#ffffff")))
                painter.drawText(box, Qt.AlignCenter, button.label)

            if self.edit_mode:
                self._paint_handles(painter, box)

        if self.edit_mode:
            self._paint_edit_hint(painter, rect)

    def _paint_handles(self, painter: QPainter, box: QRectF) -> None:
        """Draw the grab handles indicating a button can be dragged."""
        painter.setPen(QPen(QColor(255, 255, 255), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(box)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(Qt.NoPen)
        for x in (box.left(), box.right()):
            painter.drawRect(QRectF(x - 2, box.center().y() - 6, 4, 12))

    def _paint_edit_hint(self, painter: QPainter, rect: QRectF) -> None:
        """Draw the edit-mode instruction line."""
        painter.setPen(QColor(255, 255, 255, 200))
        font = QFont(self.font())
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(
            QRectF(rect.x() + 8, rect.bottom() - 28, rect.width() - 16, 20),
            Qt.AlignLeft,
            "Edit HUD: drag to move, drag an edge to resize, "
            "drag the strip's base to change its height.",
        )

    # --- Editing ----------------------------------------------------------

    def _grab_at(self, pos: QPointF) -> tuple[str | None, HudButton | None]:
        """Identify what is under the cursor.

        Returns ``(kind, button)`` where kind is ``"left"``, ``"right"``,
        ``"move"``, ``"band"`` or ``None``.
        """
        if self.hud is None:
            return (None, None)
        fw, fh = self._frame_size

        for button, (x1, y1, x2, y2) in self.hud.rects(fw, fh):
            left = self._to_widget(x1, y1).x()
            right = self._to_widget(x2, y1).x()
            top = self._to_widget(x1, y1).y()
            bottom = self._to_widget(x1, y2).y()
            if top <= pos.y() <= bottom:
                if abs(pos.x() - left) <= EDGE_GRAB:
                    return ("left", button)
                if abs(pos.x() - right) <= EDGE_GRAB:
                    return ("right", button)
                if left <= pos.x() <= right:
                    return ("move", button)

        # Not on a button: the bottom edge of the strip resizes the strip.
        band_bottom = self._to_widget(0, self.hud.band_height(fh)).y()
        if abs(pos.y() - band_bottom) <= EDGE_GRAB:
            return ("band", None)
        return (None, None)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.edit_mode:
            return
        if self._drag is None:
            kind, _ = self._grab_at(event.position())
            cursors = {"left": Qt.SizeHorCursor, "right": Qt.SizeHorCursor,
                       "move": Qt.OpenHandCursor, "band": Qt.SizeVerCursor}
            self.setCursor(cursors.get(kind, Qt.CrossCursor))
            return

        kind, button, grab_offset = self._drag
        fw, fh = self._frame_size
        fx, fy = self._to_frame(event.position())
        x_pct = fx / fw if fw else 0.0

        if kind == "band":
            # Clamped so the strip can neither fill the frame nor vanish.
            self.hud.band_pct = min(0.5, max(0.03, fy / fh if fh else 0.135))
        elif kind == "move":
            width = button.x2_pct - button.x1_pct
            new_x1 = min(1.0 - width, max(0.0, x_pct - grab_offset))
            button.x1_pct, button.x2_pct = new_x1, new_x1 + width
        elif kind == "left":
            button.x1_pct = min(button.x2_pct - MIN_WIDTH_PCT, max(0.0, x_pct))
        elif kind == "right":
            button.x2_pct = max(button.x1_pct + MIN_WIDTH_PCT, min(1.0, x_pct))

        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.edit_mode or event.button() != Qt.LeftButton:
            return
        kind, button = self._grab_at(event.position())
        if kind is None:
            return
        fw = self._frame_size[0]
        fx, _ = self._to_frame(event.position())
        # The offset within the button, so a moved button does not jump its
        # left edge to the cursor.
        offset = (fx / fw - button.x1_pct) if (button and fw) else 0.0
        self._drag = (kind, button, offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag is not None:
            self._drag = None
            self.layout_changed.emit()
