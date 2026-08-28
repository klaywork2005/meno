"""The computer-vision pipeline, one frame at a time.

Per frame: mirror, threshold in HSV, clean the mask, take the largest blob's
centroid as the pen tip, then either press a button or extend a stroke.

The palette and toolbar geometry come from a :class:`~meno.hud.HudLayout`
passed in at construction, which is what allows the HUD to be edited at
runtime. The toolbar is not drawn into the pixels; the front end draws it over
the video, so the paint canvas contains only artwork.

:class:`AirCanvas` performs no I/O.
"""

from __future__ import annotations

from collections import deque

import cv2 as cv
import numpy as np

from .hud import HudLayout

# Maximum number of points retained per stroke. Older points fall off the tail
# of the deque, bounding memory use over a long session.
TRAIL_LENGTH = 1024

# Size of the standalone paint canvas: (height, width, channels).
CANVAS_SIZE = (480, 640, 3)

# Structuring element for morphological clean-up of the mask. 5x5 is large
# enough to remove webcam speckle and small enough to leave a fingertip-sized
# blob intact.
KERNEL = np.ones((5, 5), np.uint8)

# Fallback HSV window, used until the front end supplies the user's preset.
DEFAULT_LOWER = (100, 83, 84)
DEFAULT_UPPER = (136, 255, 255)

# Stroke width in pixels, on both the frame overlay and the paint canvas.
STROKE_WIDTH = 2

Point = tuple[int, int]
Bgr = tuple[int, int, int]


class AirCanvas:
    """Holds the strokes, the selected colour and the HSV thresholds.

    Has no knowledge of where frames originate or where they are displayed.
    """

    def __init__(self, hud: HudLayout,
                 canvas_size: tuple[int, int, int] = CANVAS_SIZE) -> None:
        self.hud = hud

        # One list of strokes per palette colour, so the palette can be a
        # configuration value rather than a constant.
        self.strokes: list[list[deque[Point]]] = []
        self._reset_strokes()

        # Selected brush colour, as an index into the palette.
        self.color_index = 0

        self.lower_hsv = np.array(DEFAULT_LOWER)
        self.upper_hsv = np.array(DEFAULT_UPPER)

        # White image holding the artwork alone, so it remains readable
        # independently of the camera feed.
        self.paint = np.zeros(canvas_size, dtype=np.uint8) + 255

        # The same strokes on a layer sized to the camera frame, plus a mask of
        # where that layer has ink, for compositing onto live video. Built
        # incrementally; see the Ink section.
        self._overlay: np.ndarray | None = None
        self._ink: np.ndarray | None = None

        # Actions a button may name. A HUD file naming an absent action is
        # ignored rather than raising in the frame loop.
        self._actions = {"clear": self.clear, "set_color": self.set_color}

    # --- Commands ---------------------------------------------------------
    # Driven both by the front end and by the on-screen toolbar.

    def set_hsv(self, lower: list[int], upper: list[int]) -> None:
        """Replace the colour window the pen is matched against."""
        self.lower_hsv = np.array(lower)
        self.upper_hsv = np.array(upper)

    def set_color(self, index: int) -> None:
        """Select the brush colour, as an index into the HUD palette."""
        if 0 <= index < len(self.strokes):
            self.color_index = index

    def clear(self) -> None:
        """Discard every stroke and reset the canvas to white."""
        self._reset_strokes()
        self.paint[:] = 255
        if self._overlay is not None:
            self._overlay[:] = 0
            self._ink[:] = 0

    def sync_palette(self) -> None:
        """Resize the stroke buffers after the palette was edited.

        Called by the front end when the HUD is reloaded. Growing the palette
        retains existing artwork; shrinking it discards the strokes whose
        colour no longer exists.
        """
        slots = self.hud.color_slots()
        while len(self.strokes) < slots:
            self.strokes.append([deque(maxlen=TRAIL_LENGTH)])
        del self.strokes[slots:]
        self.color_index = min(self.color_index, slots - 1)
        self._repaint_all()

    def _reset_strokes(self) -> None:
        self.strokes = [[deque(maxlen=TRAIL_LENGTH)]
                        for _ in range(self.hud.color_slots())]

    # --- Pipeline ---------------------------------------------------------

    def process(self, frame: np.ndarray
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Run one camera frame through the pipeline.

        Returns ``(frame, paint, mask)``: the frame with the pen outline and
        strokes drawn on it, the artwork alone, and the binary mask.
        """
        # Mirrored so that on-screen motion matches hand motion.
        frame = cv.flip(frame, 1)
        h, w = frame.shape[:2]
        self._ensure_overlay(h, w)

        # cvtColor returns a new array, so drawing on `frame` afterwards leaves
        # `hsv` unmodified and the pen outline cannot be detected as the pen.
        hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)

        mask = self._mask(hsv)
        center = self._find_pen(mask, frame)

        if center is not None:
            if center[1] <= self.hud.band_height(h):
                self._press(center, w, h)
            else:
                self._extend_stroke(center)
        else:
            self._pen_up()

        self._render(frame)
        return frame, self.paint, mask

    def _mask(self, hsv: np.ndarray) -> np.ndarray:
        """Return a binary mask that is white inside the HSV window."""
        mask = cv.inRange(hsv, self.lower_hsv, self.upper_hsv)
        mask = cv.erode(mask, KERNEL, iterations=1)           # remove speckles
        mask = cv.morphologyEx(mask, cv.MORPH_OPEN, KERNEL)   # erode + dilate
        mask = cv.dilate(mask, KERNEL, iterations=1)          # restore blob size
        return mask

    def _find_pen(self, mask: np.ndarray, frame: np.ndarray) -> Point | None:
        """Return the pen tip centroid, or ``None`` if the object is not
        visible. Outlines the blob on ``frame``.
        """
        # RETR_EXTERNAL keeps only outer contours; CHAIN_APPROX_SIMPLE stores
        # corner points rather than every pixel.
        cnts, _ = cv.findContours(mask.copy(), cv.RETR_EXTERNAL,
                                  cv.CHAIN_APPROX_SIMPLE)
        if len(cnts) == 0:
            return None

        # The largest blob is taken as the pen; smaller ones are other objects
        # sharing its colour.
        cnt = sorted(cnts, key=cv.contourArea, reverse=True)[0]
        ((x, y), radius) = cv.minEnclosingCircle(cnt)
        cv.circle(frame, (int(x), int(y)), int(radius), (0, 255, 255), 2)

        # Image moments give the centroid: m10/m00 and m01/m00 are the mean x
        # and y of the blob's pixels. m00 is the area, so zero indicates a
        # degenerate contour and must be guarded before dividing.
        M = cv.moments(cnt)
        if M["m00"] == 0:
            return None
        return (int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"]))

    def _press(self, center: Point, frame_w: int, frame_h: int) -> None:
        """Handle a pen tip inside the toolbar band as a button press."""
        button = self.hud.hit(center[0], center[1], frame_w, frame_h)
        if button is None:
            return
        handler = self._actions.get(button.action)
        if handler is None:
            return
        handler() if button.arg is None else handler(button.arg)

    def _extend_stroke(self, center: Point) -> None:
        """Append a point to the stroke in progress and ink the new segment.

        appendleft keeps the newest point at index 0, so the point to join to
        is whatever is currently at the front.
        """
        stroke = self.strokes[self.color_index][-1]
        previous = stroke[0] if stroke else None
        stroke.appendleft(center)
        if previous is not None:
            self._ink_segment(previous, center,
                              self.hud.palette_bgr()[self.color_index])

    def _pen_up(self) -> None:
        """Open a new empty stroke for every colour.

        Called when no matching object is visible. Without it, lifting the pen
        and replacing it elsewhere would join the two positions with one line.
        """
        for stroke_list in self.strokes:
            # Appending to an already-empty stroke would grow the list without
            # bound while the pen is out of frame.
            if stroke_list[-1]:
                stroke_list.append(deque(maxlen=TRAIL_LENGTH))

    # --- Ink --------------------------------------------------------------
    # The artwork is stored as pixels rather than replayed from points.
    #
    # Replaying every segment of every stroke onto the frame and the paint
    # canvas each frame costs O(points drawn so far) cv.line calls per frame,
    # so per-frame cost grows for the duration of the session; it also redraws
    # the paint canvas with lines already present on it.
    #
    # Instead each segment is inked once, when it is made, into a layer sized
    # to the frame. Display is then one masked copy, at a cost independent of
    # how much has been drawn.

    def _ensure_overlay(self, h: int, w: int) -> None:
        """Allocate or resize the ink layer to match the frame size."""
        if self._overlay is not None and self._overlay.shape[:2] == (h, w):
            return
        self._overlay = np.zeros((h, w, 3), dtype=np.uint8)
        self._ink = np.zeros((h, w), dtype=np.uint8)
        self._repaint_all()

    def _ink_segment(self, start: Point, end: Point, color: Bgr) -> None:
        """Draw one segment onto the artwork and onto the ink layer."""
        cv.line(self.paint, start, end, color, STROKE_WIDTH)
        if self._overlay is not None:
            cv.line(self._overlay, start, end, color, STROKE_WIDTH)
            # The companion mask records where ink exists, so the colour can be
            # composited without also compositing the layer's black background.
            cv.line(self._ink, start, end, 255, STROKE_WIDTH)

    def _repaint_all(self) -> None:
        """Rebuild the artwork from the stored strokes.

        Required only when the pixels no longer correspond to the points: the
        frame changed size, or the palette was edited.
        """
        self.paint[:] = 255
        if self._overlay is None:
            return
        self._overlay[:] = 0
        self._ink[:] = 0
        palette = self.hud.palette_bgr()
        for color_index, stroke_list in enumerate(self.strokes):
            color = palette[color_index]
            for stroke in stroke_list:
                for k in range(1, len(stroke)):
                    self._ink_segment(stroke[k - 1], stroke[k], color)

    def _render(self, frame: np.ndarray) -> None:
        """Composite the ink layer onto the frame wherever ink exists."""
        if self._ink is None:
            return
        np.copyto(frame, self._overlay, where=self._ink[:, :, None] > 0)
