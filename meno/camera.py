"""Webcam device access: opening, configuring and enumerating cameras.

Contains no Qt imports.

Three device-level constraints are handled here:

* On Windows the default MSMF backend can take seconds to open a device and
  fails on some cameras that DirectShow opens. ``CAP_DSHOW`` is requested
  explicitly.
* Enumeration costs one backend timeout per index that is not a camera, so it
  is done on demand and never on the thread drawing the UI.
* Auto-exposure lowers the frame rate. In low light a webcam lengthens its
  integration time, turning a 33ms frame into an 80ms one and 30fps into 12.
  Pinning the exposure prevents this and also keeps colours constant, which
  the HSV thresholds depend on.
"""

from __future__ import annotations

import sys

import cv2 as cv

# DirectShow on Windows; OpenCV's choice elsewhere.
BACKEND = cv.CAP_DSHOW if sys.platform == "win32" else cv.CAP_ANY

# Requested capture format. The pipeline works at the paint canvas size, so a
# larger frame would only be scaled back down.
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
TARGET_FPS = 30

# DirectShow exposure is logarithmic and signed: -6 is roughly 1/64s, which
# permits 30fps; -4 is roughly 1/16s and caps around 15fps.
DEFAULT_EXPOSURE = -6
EXPOSURE_RANGE = (-11, -2)

# Backend-specific values of CAP_PROP_AUTO_EXPOSURE. DirectShow uses a
# normalised 0.25/0.75 pair; V4L2 uses 1 for manual and 3 for aperture
# priority. A wrong value fails silently - the property does not take effect.
_MANUAL_AUTO_EXPOSURE = 0.25 if sys.platform == "win32" else 1
_AUTO_AUTO_EXPOSURE = 0.75 if sys.platform == "win32" else 3


def configure(cap: cv.VideoCapture, *, lock_exposure: bool = True,
              exposure: int = DEFAULT_EXPOSURE) -> None:
    """Apply the capture settings that affect frame rate.

    Each setting is a request. A device may ignore any of them and report a
    different value, so no return value is checked; the frame loop uses
    whatever the device supplies.
    """
    cap.set(cv.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv.CAP_PROP_FPS, TARGET_FPS)

    # A deep driver buffer delays the returned frame by several frames.
    cap.set(cv.CAP_PROP_BUFFERSIZE, 1)

    set_exposure(cap, lock_exposure, exposure)


def set_exposure(cap: cv.VideoCapture, lock: bool,
                 exposure: int = DEFAULT_EXPOSURE) -> None:
    """Pin the exposure to ``exposure``, or restore automatic exposure.

    Order is significant: auto-exposure must be disabled before a manual
    exposure takes effect, and re-enabled after, or the device continues to
    use the manual value.
    """
    if lock:
        cap.set(cv.CAP_PROP_AUTO_EXPOSURE, _MANUAL_AUTO_EXPOSURE)
        cap.set(cv.CAP_PROP_EXPOSURE, exposure)
    else:
        cap.set(cv.CAP_PROP_AUTO_EXPOSURE, _AUTO_AUTO_EXPOSURE)


def describe(cap: cv.VideoCapture) -> str:
    """Return the device's actual resolution and codec, e.g. ``640 x 480 YUY2``."""
    fourcc = int(cap.get(cv.CAP_PROP_FOURCC))
    codec = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip()
    return "%d x %d %s" % (cap.get(cv.CAP_PROP_FRAME_WIDTH),
                           cap.get(cv.CAP_PROP_FRAME_HEIGHT), codec)


def open_camera(index: int, *, lock_exposure: bool = True,
                exposure: int = DEFAULT_EXPOSURE) -> cv.VideoCapture | None:
    """Open camera ``index``, or return ``None`` if it cannot be read from.

    ``isOpened()`` is not sufficient: a device held by another application
    reports open and then fails on the first read, so the first frame is used
    as the test.
    """
    cap = cv.VideoCapture(index, BACKEND)
    if not cap.isOpened():
        cap.release()
        return None

    configure(cap, lock_exposure=lock_exposure, exposure=exposure)

    ok, _ = cap.read()
    if not ok:
        cap.release()
        return None
    return cap


def available_cameras(limit: int = 5,
                      skip: tuple[int, ...] = ()) -> list[int]:
    """Return the indices below ``limit`` that can be opened.

    Costs one backend timeout per index that is not a camera, so it must not
    run on the UI thread.

    ``skip`` lists indices already known to be cameras, in particular the one
    currently open. Probing an in-use device wastes time and some drivers
    refuse the second handle.
    """
    found = []
    for index in range(limit):
        if index in skip:
            found.append(index)
            continue
        cap = cv.VideoCapture(index, BACKEND)
        if cap.isOpened():
            found.append(index)
        cap.release()
    return sorted(found)


CAMERA_HELP = (
    "Meno could not open a camera.\n\n"
    "Things to check:\n"
    "  - Another app (Teams, Zoom, the Camera app) may be holding it.\n"
    "  - Windows Settings > Privacy & security > Camera, and make sure\n"
    "    'Let desktop apps access your camera' is on.\n"
    "  - If you have more than one camera, try another index from the\n"
    "    Camera menu."
)
