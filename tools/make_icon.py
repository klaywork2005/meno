"""Generate ``meno/assets/meno.ico``, used by the application, the executable
and the installer.

The icon is drawn from the palette in the default theme, so it stays
consistent with the shipped HUD colours. Run after changing the theme::

    python tools/make_icon.py

The output is a multi-size ICO. Windows selects the size it needs: 16px in the
title bar, 32px on the desktop, 256px in large-icon views. Each size is drawn
at its own resolution rather than downscaled from one large image, because a
stroke tuned for 256px does not remain legible at 16px.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import cv2 as cv
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
THEME = ROOT / "meno" / "assets" / "themes" / "default.json"
TARGET = ROOT / "meno" / "assets" / "meno.ico"

# The sizes Windows requests.
SIZES = (16, 24, 32, 48, 64, 128, 256)

# Tile background, in BGR. Matches the video views' backdrop.
BACKGROUND = (24, 24, 27)

# Supersampling factor. Each image is drawn this many times larger and then
# reduced with INTER_AREA, which antialiases the result.
SUPERSAMPLE = 4


def hex_to_bgr(value: str) -> tuple[int, int, int]:
    """Convert ``"#rrggbb"`` to OpenCV's ``(b, g, r)`` order."""
    value = value.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return (b, g, r)


def palette() -> list[tuple[int, int, int]]:
    """Read the brush colours from the shipped theme."""
    theme = json.loads(THEME.read_text(encoding="utf-8"))
    return [hex_to_bgr(c) for c in theme["palette"]]


def rounded_mask(size: int) -> np.ndarray:
    """Return an alpha channel shaped as a rounded square."""
    big = size * SUPERSAMPLE
    mask = np.zeros((big, big), np.uint8)
    radius = int(big * 0.22)
    cv.rectangle(mask, (radius, 0), (big - radius, big), 255, -1)
    cv.rectangle(mask, (0, radius), (big, big - radius), 255, -1)
    for cx, cy in ((radius, radius), (big - radius, radius),
                   (radius, big - radius), (big - radius, big - radius)):
        cv.circle(mask, (cx, cy), radius, 255, -1)
    return cv.resize(mask, (size, size), interpolation=cv.INTER_AREA)


def draw(size: int) -> np.ndarray:
    """Render one BGRA icon: a multi-colour stroke on a dark tile."""
    big = size * SUPERSAMPLE
    img = np.zeros((big, big, 3), np.uint8)
    img[:] = BACKGROUND

    colors = palette()
    # A sine sweep, sampled densely enough that consecutive points overlap and
    # the line reads as one continuous stroke.
    xs = np.linspace(big * 0.14, big * 0.86, 240)
    ys = big * 0.5 + np.sin(np.linspace(-1.9, 1.9, 240)) * big * 0.24
    points = np.stack([xs, ys], axis=1).astype(np.int32)

    thickness = max(1, int(big * 0.115))
    for i in range(1, len(points)):
        # Colour changes along the stroke, in palette order.
        color = colors[min(int(i / len(points) * len(colors)), len(colors) - 1)]
        cv.line(img, tuple(points[i - 1]), tuple(points[i]), color,
                thickness, cv.LINE_AA)

    img = cv.resize(img, (size, size), interpolation=cv.INTER_AREA)
    return np.dstack([img, rounded_mask(size)])


def write_ico(images: list[np.ndarray], path: Path) -> None:
    """Write a PNG-compressed ICO.

    Windows Vista and later read PNG-in-ICO, which is smaller than the older
    BMP-with-AND-mask format. Layout: a 6-byte header, one 16-byte directory
    entry per image, then the image data.
    """
    encoded = []
    for img in images:
        ok, buf = cv.imencode(".png", img)
        if not ok:
            raise RuntimeError("could not encode a %dpx icon" % img.shape[0])
        encoded.append(buf.tobytes())

    header = struct.pack("<HHH", 0, 1, len(encoded))  # reserved, type 1 = icon
    offset = len(header) + 16 * len(encoded)
    entries, blobs = b"", b""
    for img, data in zip(images, encoded):
        size = img.shape[0]
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # the field is one byte; 0 means 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)

    path.write_bytes(header + entries + blobs)


def main() -> int:
    """Write the icon. Returns a process exit code."""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    write_ico([draw(size) for size in SIZES], TARGET)
    print("wrote %s (%d bytes)" % (TARGET, TARGET.stat().st_size))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
