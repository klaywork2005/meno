"""Main window and drawing controls."""

import cv2 as cv
import numpy as np
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..capture import CaptureThread
from ..config import asset_path
from ..hud import HudLayout
from ..vision import AirCanvas, DEFAULT_LOWER, DEFAULT_UPPER
from .video_view import FrameView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Meno")
        self.resize(1180, 760)

        hud = HudLayout.load(asset_path("themes", "default.json"))
        self.canvas = AirCanvas(hud)
        self.live = FrameView(hud)
        self.paint_view = FrameView()
        self.mask_view = FrameView()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        controls = QHBoxLayout()
        layout.addLayout(controls)

        controls.addWidget(QLabel("Camera"))
        self.camera_box = QComboBox()
        self.camera_box.addItems([str(index) for index in range(5)])
        controls.addWidget(self.camera_box)
        open_button = QPushButton("Open camera")
        open_button.clicked.connect(self._open_camera)
        controls.addWidget(open_button)

        self.show_paint = QCheckBox("Canvas")
        self.show_paint.setChecked(True)
        self.show_mask = QCheckBox("Mask")
        controls.addWidget(self.show_paint)
        controls.addWidget(self.show_mask)
        controls.addStretch()

        clear_button = QPushButton("Clear")
        clear_button.setShortcut("Ctrl+L")
        clear_button.clicked.connect(self._clear_canvas)
        save_button = QPushButton("Save canvas")
        save_button.setShortcut("Ctrl+S")
        save_button.clicked.connect(self._save_canvas)
        controls.addWidget(clear_button)
        controls.addWidget(save_button)

        views = QHBoxLayout()
        layout.addLayout(views, 1)
        views.addWidget(self.live, 2)
        self.previews = QWidget()
        previews = QVBoxLayout(self.previews)
        previews.setContentsMargins(0, 0, 0, 0)
        previews.addWidget(self.paint_view)
        previews.addWidget(self.mask_view)
        views.addWidget(self.previews, 1)
        self.show_paint.toggled.connect(self._update_views)
        self.show_mask.toggled.connect(self._update_views)
        self._update_views()

        thresholds = QHBoxLayout()
        layout.addLayout(thresholds)
        self.hsv_inputs = []
        for title, values in (("Lower", DEFAULT_LOWER), ("Upper", DEFAULT_UPPER)):
            form = QFormLayout()
            thresholds.addLayout(form)
            for name, maximum, value in zip(
                ("Hue", "Saturation", "Value"), (180, 255, 255), values
            ):
                field = QSpinBox()
                field.setRange(0, maximum)
                field.setValue(value)
                field.valueChanged.connect(self._update_hsv)
                form.addRow(f"{title} {name}", field)
                self.hsv_inputs.append(field)
        layout.addWidget(QLabel(
            "Show the mask and adjust the colour range until only your object is white."
        ))

        self.capture = CaptureThread(self)
        self.capture.frame_ready.connect(self._on_frame)
        self.capture.opened.connect(self._camera_opened)
        self.capture.open_failed.connect(self._camera_failed)
        self.capture.lost.connect(self._camera_lost)
        self.capture.finished.connect(self.close)
        self.capture.start()
        self._open_camera()

    def _update_views(self) -> None:
        self.paint_view.setVisible(self.show_paint.isChecked())
        self.mask_view.setVisible(self.show_mask.isChecked())
        self.previews.setVisible(
            self.show_paint.isChecked() or self.show_mask.isChecked()
        )
        self.paint_view.set_frame(self.canvas.paint)

    def _update_hsv(self) -> None:
        values = [field.value() for field in self.hsv_inputs]
        self.canvas.set_hsv(values[:3], values[3:])

    def _open_camera(self) -> None:
        index = self.camera_box.currentIndex()
        self.statusBar().showMessage(f"Opening camera {index}...")
        self.capture.open(index)

    def _camera_opened(self, index: int, description: str) -> None:
        self.statusBar().showMessage(f"Camera {index}: {description}")

    def _camera_failed(self, index: int) -> None:
        self.statusBar().showMessage(
            f"Could not open camera {index}. Try another camera, close other camera "
            "apps, or check camera permissions."
        )

    def _camera_lost(self) -> None:
        self.statusBar().showMessage("Camera disconnected. Click Open camera to reconnect.")

    def _on_frame(self, frame: np.ndarray) -> None:
        try:
            frame, paint, mask = self.canvas.process(frame)
            self.live.active_index = self.canvas.color_index
            self.live.set_frame(frame)
            if self.show_paint.isChecked():
                self.paint_view.set_frame(paint)
            if self.show_mask.isChecked():
                self.mask_view.set_frame(mask)
        finally:
            # Allow the worker to deliver the next frame.
            self.capture.frame_consumed()

    def _clear_canvas(self) -> None:
        self.canvas.clear()
        self.paint_view.set_frame(self.canvas.paint)

    def _save_canvas(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save canvas", "drawing.png",
            "PNG image (*.png);;JPEG image (*.jpg)"
        )
        if not path:
            return
        try:
            saved = cv.imwrite(path, self.canvas.paint)
        except cv.error:
            saved = False
        if saved:
            self.statusBar().showMessage(f"Saved {path}")
        else:
            QMessageBox.warning(self, "Save failed", "Could not save the canvas.")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.capture.stop()
        if self.capture.isRunning():
            # Keep the window alive until the camera has been released.
            self.setEnabled(False)
            self.statusBar().showMessage("Closing camera...")
            event.ignore()
        else:
            event.accept()
