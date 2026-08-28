"""The main window: docks, menus, controls and the per-frame handler.

The live feed is the central widget; the paint canvas, the mask and the control
panel are docks, so they can be arranged, hidden and remembered.

Capture runs on :class:`~meno.capture.CaptureThread` and frames arrive by
signal. This class only processes and paints; it performs no blocking calls.
See meno/capture.py for why.

This module uses only the commands ``AirCanvas`` already exposes - ``set_hsv``,
``set_color``, ``clear`` - so the front end can be replaced without changing
the pipeline.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import cv2 as cv
import numpy as np
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import (QAction, QActionGroup, QCloseEvent,
                           QDesktopServices, QKeySequence)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDockWidget, QFileDialog,
                               QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QMainWindow, QMenu, QMessageBox, QPushButton,
                               QSlider, QVBoxLayout, QWidget)

from .. import camera, config
from ..capture import CaptureThread
from ..hud import HudLayout
from ..vision import AirCanvas
from .video_view import FrameView

# The six thresholds, in panel order, with their maximums. Hue is 0-180 in
# OpenCV - half the usual 0-360, so it fits in a byte - while saturation and
# value are 0-255.
SLIDERS = [
    ("Lower Hue", 180), ("Lower Saturation", 255), ("Lower Value", 255),
    ("Upper Hue", 180), ("Upper Saturation", 255), ("Upper Value", 255),
]

# Refresh interval of the status bar frame counter.
FPS_INTERVAL_MS = 1000

# Maximum time to wait for the capture thread to finish on close.
SHUTDOWN_WAIT_MS = 3000


class MainWindow(QMainWindow):
    """Top-level window and frame-loop consumer."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Meno")
        self.resize(1180, 760)

        self.settings = config.load_settings()
        self.hud = HudLayout.load(config.ensure_user_hud())
        self.canvas = AirCanvas(self.hud)

        self.live = FrameView(hud=self.hud, show_hud=True)
        self.live.layout_changed.connect(self._save_hud)
        self.setCentralWidget(self.live)

        self.paint_view = FrameView()
        self.mask_view = FrameView()

        # Known camera indices, populated by a background scan so that opening
        # the Camera menu does not wait for one.
        self._cameras: list[int] = []
        self._scanning = False
        self._camera_group: QActionGroup | None = None
        self._camera_status = ""

        self._build_docks()
        self._build_menus()

        self._apply_preset(self.settings.get("preset"))

        self._start_capture()

        # Frames delivered, sampled once a second.
        self._frames = 0
        self._fps_since = time.perf_counter()
        self.fps_timer = QTimer(self)
        self.fps_timer.timeout.connect(self._update_fps)
        self.fps_timer.start(FPS_INTERVAL_MS)

    # --- Construction -----------------------------------------------------

    def _build_docks(self) -> None:
        """Create the paint, mask and control docks."""
        self.paint_dock = QDockWidget("Paint", self)
        self.paint_dock.setWidget(self.paint_view)
        self.addDockWidget(Qt.RightDockWidgetArea, self.paint_dock)

        self.mask_dock = QDockWidget("Mask", self)
        self.mask_dock.setWidget(self.mask_view)
        self.addDockWidget(Qt.RightDockWidgetArea, self.mask_dock)

        self.controls_dock = QDockWidget("Controls", self)
        self.controls_dock.setWidget(self._build_controls())
        self.addDockWidget(Qt.LeftDockWidgetArea, self.controls_dock)

        self.paint_dock.setVisible(self.settings.get("show_paint", True))
        self.mask_dock.setVisible(self.settings.get("show_mask", False))

    def _build_controls(self) -> QWidget:
        """Build the control panel: presets, the six HSV sliders and the
        exposure controls."""
        panel = QWidget()
        layout = QVBoxLayout(panel)

        preset_row = QHBoxLayout()
        self.preset_box = QComboBox()
        self.preset_box.addItems(sorted(self.settings["presets"]))
        self.preset_box.currentTextChanged.connect(self._apply_preset)
        save_preset = QPushButton("Save as...")
        save_preset.clicked.connect(self._save_preset)
        preset_row.addWidget(self.preset_box, 1)
        preset_row.addWidget(save_preset)
        layout.addWidget(QLabel("Preset"))
        layout.addLayout(preset_row)

        form = QFormLayout()
        self.sliders: dict[str, QSlider] = {}
        for name, maximum in SLIDERS:
            slider = QSlider(Qt.Horizontal)
            slider.setRange(0, maximum)
            slider.valueChanged.connect(self._push_hsv)
            value = QLabel("0")
            slider.valueChanged.connect(lambda v, lbl=value: lbl.setText(str(v)))
            row = QHBoxLayout()
            row.addWidget(slider, 1)
            row.addWidget(value)
            holder = QWidget()
            holder.setLayout(row)
            form.addRow(name, holder)
            self.sliders[name] = slider
        layout.addLayout(form)

        layout.addWidget(QLabel(
            "Tune until only your object is white in the Mask view."))

        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>Camera</b>"))
        layout.addWidget(self._build_exposure_controls())

        layout.addStretch(1)
        return panel

    def _build_exposure_controls(self) -> QWidget:
        """Build the exposure lock checkbox and brightness slider.

        Auto-exposure lengthens the camera's integration time in low light,
        which lowers the frame rate. Locking it trades brightness for frame
        rate; the slider sets the fixed exposure. See meno.camera.
        """
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)

        self.lock_exposure_box = QCheckBox("Lock exposure (higher frame rate)")
        self.lock_exposure_box.setChecked(
            self.settings.get("lock_exposure", True))
        self.lock_exposure_box.setToolTip(
            "Auto-exposure slows the camera down in dim light. Locking it "
            "keeps the frame rate up and the colours steady.")
        self.lock_exposure_box.toggled.connect(self._push_exposure)
        layout.addWidget(self.lock_exposure_box)

        low, high = camera.EXPOSURE_RANGE
        self.exposure_slider = QSlider(Qt.Horizontal)
        self.exposure_slider.setRange(low, high)
        self.exposure_slider.setValue(self.settings.get("exposure", -6))
        self.exposure_slider.valueChanged.connect(self._push_exposure)
        row = QHBoxLayout()
        row.addWidget(QLabel("Darker"))
        row.addWidget(self.exposure_slider, 1)
        row.addWidget(QLabel("Brighter"))
        layout.addLayout(row)

        self.exposure_slider.setEnabled(self.lock_exposure_box.isChecked())
        self.lock_exposure_box.toggled.connect(self.exposure_slider.setEnabled)
        return box

    def _build_menus(self) -> None:
        """Create the menu bar."""
        file_menu = self.menuBar().addMenu("&File")
        self._add(file_menu, "&Save canvas...", self._save_canvas,
                  QKeySequence.Save)
        self._add(file_menu, "&Clear canvas", self.canvas.clear, "Ctrl+L")
        file_menu.addSeparator()
        self._add(file_menu, "E&xit", self.close, QKeySequence.Quit)

        view_menu = self.menuBar().addMenu("&View")
        for dock in (self.paint_dock, self.mask_dock, self.controls_dock):
            view_menu.addAction(dock.toggleViewAction())

        self.camera_menu = self.menuBar().addMenu("&Camera")
        # Rebuilt from the cached scan result. The scan itself runs on the
        # capture thread; running it here would block the menu from painting.
        self.camera_menu.aboutToShow.connect(self._rebuild_camera_menu)
        self._rebuild_camera_menu()

        hud_menu = self.menuBar().addMenu("&HUD")
        self.edit_action = self._add(hud_menu, "&Edit layout",
                                     self._toggle_edit, "Ctrl+E",
                                     checkable=True)
        self._add(hud_menu, "&Reload from disk", self._reload_hud)
        self._add(hud_menu, "Reset to &default", self._reset_hud)
        hud_menu.addSeparator()
        self._add(hud_menu, "Open config &folder", self._open_config_folder)

        help_menu = self.menuBar().addMenu("&Help")
        self._add(help_menu, "&About", self._about)

    def _add(self, menu: QMenu, text: str, slot: Callable[..., object],
             shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
             checkable: bool = False) -> QAction:
        """Create an action, connect it and add it to ``menu``."""
        action = QAction(text, self, checkable=checkable)
        action.triggered.connect(slot)
        if shortcut:
            action.setShortcut(shortcut)
        menu.addAction(action)
        return action

    # --- The frame loop ---------------------------------------------------

    def _start_capture(self) -> None:
        """Start the capture thread and request the stored camera."""
        self.capture = CaptureThread(self)
        self.capture.frame_ready.connect(self._on_frame)
        self.capture.opened.connect(self._on_camera_opened)
        self.capture.open_failed.connect(self._on_camera_failed)
        self.capture.lost.connect(self._on_camera_lost)
        self.capture.cameras_found.connect(self._on_cameras_found)
        self.capture.start()

        self._push_exposure()
        self.capture.open(self.settings.get("camera_index", 0))
        # Scan now, in the background, so the Camera menu has a device list
        # the first time it is opened.
        self._request_scan()

    def _on_frame(self, frame: np.ndarray) -> None:
        """Process and display one frame from the capture thread."""
        try:
            frame, paint, mask = self.canvas.process(frame)

            self.live.set_active_index(self.canvas.color_index)
            self.live.set_frame(frame)
            # Pixmap conversion is not free, so hidden views are not updated.
            if self.paint_dock.isVisible():
                self.paint_view.set_frame(paint)
            if self.mask_dock.isVisible():
                self.mask_view.set_frame(mask)
            self._frames += 1
        finally:
            # Until this runs the worker drops frames rather than queueing
            # them, so skipping it on an exception would stop video for good.
            self.capture.frame_consumed()

    def _update_fps(self) -> None:
        """Refresh the status bar frame counter."""
        now = time.perf_counter()
        elapsed = now - self._fps_since
        if self._camera_status:
            # Opening a device produces a second or more with no frames; a
            # displayed "0 fps" during it would read as a fault.
            if self._frames and elapsed > 0:
                self.statusBar().showMessage("%s - %.0f fps" % (
                    self._camera_status, self._frames / elapsed))
            else:
                self.statusBar().showMessage(self._camera_status)
        self._frames, self._fps_since = 0, now

    # --- Camera -----------------------------------------------------------

    def _open_camera(self, index: int) -> None:
        """Request a camera. Returns immediately; the result arrives by signal."""
        self._camera_status = ""
        self.statusBar().showMessage("Opening camera %d..." % index)
        self.capture.open(index)

    def _on_camera_opened(self, index: int, description: str) -> None:
        self.settings["camera_index"] = index
        self._camera_status = "Camera %d - %s" % (index, description)
        if index not in self._cameras:
            self._cameras = sorted(self._cameras + [index])

    def _on_camera_failed(self, index: int) -> None:
        self._camera_status = ""
        self.statusBar().showMessage("Could not open camera %d." % index)
        QMessageBox.warning(self, "No camera", camera.CAMERA_HELP)

    def _on_camera_lost(self) -> None:
        self._camera_status = ""
        self.statusBar().showMessage(
            "Lost the camera. Pick one from the Camera menu to reconnect.")

    def _request_scan(self) -> None:
        """Ask the capture thread to enumerate devices."""
        if self._scanning:
            return
        self._scanning = True
        self.capture.scan()

    def _on_cameras_found(self, indices: list[int]) -> None:
        self._scanning = False
        self._cameras = indices
        # Rebuilding a menu that is on screen would make it flicker;
        # aboutToShow rebuilds it the next time it opens.
        if not self.camera_menu.isVisible():
            self._rebuild_camera_menu()

    def _rebuild_camera_menu(self) -> None:
        """Rebuild the Camera menu from the cached device list.

        Contains no device access.
        """
        self.camera_menu.clear()
        if self._camera_group is not None:
            # clear() deleted the actions but not the group, and one group per
            # menu opening accumulates over a session.
            self._camera_group.deleteLater()
        self._camera_group = QActionGroup(self.camera_menu)
        self._camera_group.setExclusive(True)

        for index in self._cameras:
            action = QAction("Camera %d" % index, self, checkable=True)
            action.setChecked(index == self.settings.get("camera_index"))
            action.triggered.connect(lambda _, i=index: self._open_camera(i))
            self._camera_group.addAction(action)
            self.camera_menu.addAction(action)

        if not self._cameras:
            placeholder = QAction(
                "Scanning..." if self._scanning else "No cameras found", self)
            placeholder.setEnabled(False)
            self.camera_menu.addAction(placeholder)

        self.camera_menu.addSeparator()
        self._add(self.camera_menu, "&Rescan devices", self._request_scan)

    def _push_exposure(self) -> None:
        """Send the exposure controls' state to the capture thread."""
        lock = self.lock_exposure_box.isChecked()
        exposure = self.exposure_slider.value()
        self.settings["lock_exposure"] = lock
        self.settings["exposure"] = exposure
        self.capture.set_exposure(lock, exposure)

    # --- HSV --------------------------------------------------------------

    def _push_hsv(self) -> None:
        """Send the slider positions to the canvas."""
        get = lambda name: self.sliders[name].value()
        self.canvas.set_hsv(
            [get("Lower Hue"), get("Lower Saturation"), get("Lower Value")],
            [get("Upper Hue"), get("Upper Saturation"), get("Upper Value")],
        )

    def _apply_preset(self, name: str) -> None:
        """Load a stored HSV preset into the sliders and the canvas."""
        preset = self.settings["presets"].get(name)
        if not preset:
            return
        self.settings["preset"] = name
        values = dict(zip(
            [s[0] for s in SLIDERS],
            list(preset["lower"]) + list(preset["upper"]),
        ))
        for slider_name, value in values.items():
            self.sliders[slider_name].blockSignals(True)
            self.sliders[slider_name].setValue(value)
            self.sliders[slider_name].blockSignals(False)
        # Signals were blocked, so the labels and the canvas did not update;
        # push once here rather than six times during the loop.
        for slider in self.sliders.values():
            slider.valueChanged.emit(slider.value())
        self._push_hsv()

    def _save_preset(self) -> None:
        """Prompt for a name and store the current slider values as a preset."""
        name, ok = QInputDialog.getText(self, "Save preset", "Name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        get = lambda n: self.sliders[n].value()
        self.settings["presets"][name] = {
            "lower": [get("Lower Hue"), get("Lower Saturation"), get("Lower Value")],
            "upper": [get("Upper Hue"), get("Upper Saturation"), get("Upper Value")],
        }
        config.save_settings(self.settings)
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItems(sorted(self.settings["presets"]))
        self.preset_box.setCurrentText(name)
        self.preset_box.blockSignals(False)

    # --- HUD --------------------------------------------------------------

    def _toggle_edit(self, enabled: bool) -> None:
        """Enable or disable HUD edit mode."""
        self.live.set_edit_mode(enabled)
        self.statusBar().showMessage(
            "Editing the HUD - changes save when you let go." if enabled
            else "HUD locked.", 4000)

    def _save_hud(self) -> None:
        """Write the HUD layout to disk."""
        self.hud.save(config.hud_path())
        self.statusBar().showMessage("HUD layout saved.", 2000)

    def _reload_hud(self) -> None:
        """Re-read the HUD file, for when it was edited in a text editor.

        The layout object is mutated in place rather than replaced, because
        the canvas and the view both hold a reference to it.
        """
        fresh = HudLayout.load(config.ensure_user_hud())
        self.hud.__dict__.update(fresh.__dict__)
        self.canvas.sync_palette()
        self.live.update()
        self.statusBar().showMessage("HUD reloaded.", 2000)

    def _reset_hud(self) -> None:
        """Restore the bundled default HUD and reload it."""
        config.reset_user_hud()
        self._reload_hud()

    def _open_config_folder(self) -> None:
        """Open the user configuration directory in the file manager."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(config.user_dir())))

    # --- File -------------------------------------------------------------

    def _save_canvas(self) -> None:
        """Prompt for a path and write the paint canvas to it."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Save canvas", str(config.user_dir() / "drawing.png"),
            "PNG image (*.png);;JPEG image (*.jpg)")
        if not path:
            return
        # The paint canvas holds artwork only; the HUD is drawn by the view and
        # is not present in these pixels.
        cv.imwrite(path, self.canvas.paint)
        self.statusBar().showMessage("Saved %s" % path, 4000)

    def _about(self) -> None:
        """Show the About dialog."""
        QMessageBox.about(
            self, "Meno",
            "<b>Meno - Air Canvas</b><br>"
            "Draw by waving a coloured object at your webcam.<br><br>"
            "HUD layout: <code>%s</code>" % config.hud_path())

    # --- Shutdown ---------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:
        self.settings["show_paint"] = self.paint_dock.isVisible()
        self.settings["show_mask"] = self.mask_dock.isVisible()
        config.save_settings(self.settings)

        self.fps_timer.stop()
        # The thread holds the camera handle; exiting with it open leaves the
        # device unavailable to the next application.
        self.capture.stop()
        self.capture.wait(SHUTDOWN_WAIT_MS)
        super().closeEvent(event)
