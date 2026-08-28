"""Camera capture on a worker thread.

``cap.read()`` blocks until the camera produces a frame - 30ms nominally, 80ms
under auto-exposure. Calling it from a timer on the GUI thread leaves that
thread unable to repaint or handle input for most of each frame interval, which
delays menu display and input handling by up to a second when device
enumeration or a device open is also queued behind it.

:class:`CaptureThread` owns the ``VideoCapture`` object exclusively, so device
enumeration cannot race the frame loop, and delivers frames to the GUI thread
by signal.

Frames are dropped rather than queued when the GUI thread falls behind: a
queued connection would otherwise accumulate a backlog that grows for the
lifetime of the session.
"""

from __future__ import annotations

import cv2 as cv
from PySide6.QtCore import QMutex, QMutexLocker, QObject, QThread, Signal

from . import camera

# Poll interval while no camera is open.
IDLE_MS = 50


class CaptureThread(QThread):
    """Reads frames from a camera and emits them to the GUI thread."""

    #: A BGR frame. Emitted at most once per :meth:`frame_consumed`.
    frame_ready = Signal(object)
    #: index, format description - the camera opened successfully.
    opened = Signal(int, str)
    #: index - the camera could not be opened.
    open_failed = Signal(int)
    #: The open camera stopped returning frames.
    lost = Signal()
    #: The result of a device scan, as a list of indices.
    cameras_found = Signal(list)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cap: cv.VideoCapture | None = None
        self._index: int | None = None

        # Written by the GUI thread and read by this one, so guarded.
        self._mutex = QMutex()
        self._running = True
        self._want_index: int | None = None
        self._want_scan = False
        self._want_exposure: tuple[bool, int] | None = None
        self._in_flight = False

        self._lock_exposure = True
        self._exposure = camera.DEFAULT_EXPOSURE

    # --- Called from the GUI thread ---------------------------------------

    def open(self, index: int) -> None:
        """Request a camera. Returns immediately; result arrives on
        :attr:`opened` or :attr:`open_failed`."""
        with QMutexLocker(self._mutex):
            self._want_index = index

    def scan(self) -> None:
        """Request a device list. Returns immediately; result arrives on
        :attr:`cameras_found`."""
        with QMutexLocker(self._mutex):
            self._want_scan = True

    def set_exposure(self, lock: bool, exposure: int) -> None:
        """Change the exposure of the open camera and of subsequent opens."""
        with QMutexLocker(self._mutex):
            self._want_exposure = (lock, exposure)

    def frame_consumed(self) -> None:
        """Signal that the GUI thread will accept another frame.

        Without this the worker would emit at camera speed regardless of what
        the GUI thread can process, and the queued connection would buffer the
        difference indefinitely.
        """
        with QMutexLocker(self._mutex):
            self._in_flight = False

    def stop(self) -> None:
        """Request termination. Call ``wait()`` afterwards."""
        with QMutexLocker(self._mutex):
            self._running = False

    # --- The worker thread ------------------------------------------------

    def run(self) -> None:
        while True:
            with QMutexLocker(self._mutex):
                if not self._running:
                    break
                index, self._want_index = self._want_index, None
                scan, self._want_scan = self._want_scan, False
                exposure, self._want_exposure = self._want_exposure, None

            # Store the exposure before opening, so a camera opened in this
            # same pass is opened with it rather than with the default.
            if exposure is not None:
                self._lock_exposure, self._exposure = exposure
            if index is not None:
                self._open(index)
            elif exposure is not None and self._cap is not None:
                camera.set_exposure(self._cap, *exposure)
            if scan:
                self._scan()

            if self._cap is None:
                self.msleep(IDLE_MS)
                continue

            ok, frame = self._cap.read()
            if not ok:
                self._release()
                self.lost.emit()
                continue

            # Drop the frame if the GUI thread has not finished with the
            # previous one. The read has already happened, so the only cost is
            # the frame itself.
            with QMutexLocker(self._mutex):
                if self._in_flight:
                    continue
                self._in_flight = True
            self.frame_ready.emit(frame)

        self._release()

    def _open(self, index: int) -> None:
        self._release()
        cap = camera.open_camera(index, lock_exposure=self._lock_exposure,
                                 exposure=self._exposure)
        if cap is None:
            self.open_failed.emit(index)
            return
        self._cap, self._index = cap, index
        # A frame may have been in flight when the previous camera was
        # released; the GUI thread will never acknowledge it, so clear the
        # flag or the new camera emits nothing.
        with QMutexLocker(self._mutex):
            self._in_flight = False
        self.opened.emit(index, camera.describe(cap))

    def _scan(self) -> None:
        """Enumerate devices without disturbing the open one."""
        skip = () if self._index is None else (self._index,)
        self.cameras_found.emit(camera.available_cameras(skip=skip))

    def _release(self) -> None:
        if self._cap is not None:
            self._cap.release()
        self._cap, self._index = None, None
