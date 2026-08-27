"""
Meno - Air Canvas
=================

A virtual whiteboard you draw on by waving a coloured object (a bottle cap, a
marker lid, a sticky note) in front of your webcam. No mouse, no touchscreen -
the tip of the object *is* the pen.

How it works
------------
Every frame goes through a short computer-vision pipeline:

1. **Capture & mirror** - grab a frame and flip it horizontally so that moving
   your hand right moves the pointer right (a raw webcam feed is mirrored).
2. **Colour segmentation** - convert BGR to HSV and threshold it against the
   Upper/Lower bounds set on the "Color detectors" trackbars. HSV separates
   *what colour* a pixel is (hue) from *how bright* it is (value), which makes
   thresholding far more robust to changing light than raw BGR would be.
3. **Noise removal** - erode, open, then dilate the binary mask so stray
   speckles disappear while the real blob keeps its original size.
4. **Blob tracking** - take the largest external contour and use its centroid
   (via image moments) as the pen tip for this frame.
5. **Interpret the position** - if the tip is inside the toolbar strip at the
   top of the screen it counts as a button press (clear / pick a colour);
   otherwise the point is appended to the stroke currently being drawn.
6. **Render** - replay every stored stroke as connected line segments onto both
   the live camera feed and the standalone paint canvas.

Stroke storage
--------------
Strokes are kept as one deque of points per stroke, grouped in a list per
colour::

    bpoints = [deque_of_stroke_0, deque_of_stroke_1, ...]

Whenever the pen leaves the frame (no contour found) a fresh deque is pushed
onto every list and the matching index is bumped. That "pen up" event is what
stops two separate strokes from being joined by one long straight line.

Usage
-----
    python main.py

Controls
--------
    Toolbar    hover the coloured object over a box to clear or switch colour
    Trackbars  tune the HSV window until only your object shows up white in
               the "Mask" window
    q          quit

Author: Klay Garcia
"""

import numpy as np
import cv2 as cv
from collections import deque

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

# Drawing palette, in OpenCV's BGR order (not RGB).
COLORS = [
    (255, 0, 0),      # 0 - blue
    (0, 255, 0),      # 1 - green
    (0, 0, 255),      # 2 - red
    (0, 255, 255),    # 3 - yellow
]

# Height in pixels of the button strip across the top of the frame. A pen tip
# with y <= TOOLBAR_HEIGHT is treated as a button press instead of a brush
# stroke, so this value has to match the rectangles drawn below.
TOOLBAR_HEIGHT = 65

# Toolbar layout. `color_index` is the palette slot a button selects; CLEAR
# uses None because it wipes the canvas instead of changing colour. Only CLEAR
# carries a text label - the rest are self-explanatory colour swatches.
BUTTONS = [
    {"label": "CLEAR", "x1": 40,  "x2": 140, "fill": (0, 0, 0), "color_index": None},
    {"label": None,    "x1": 160, "x2": 255, "fill": COLORS[0], "color_index": 0},
    {"label": None,    "x1": 275, "x2": 370, "fill": COLORS[1], "color_index": 1},
    {"label": None,    "x1": 390, "x2": 485, "fill": COLORS[2], "color_index": 2},
    {"label": None,    "x1": 505, "x2": 600, "fill": COLORS[3], "color_index": 3},
]

# Maximum number of points remembered per stroke. Older points fall off the
# tail of the deque, which caps memory use during a long session.
TRAIL_LENGTH = 1024

# Size of the standalone paint canvas: (height, width, channels).
CANVAS_SIZE = (480, 640, 3)

# First canvas row that CLEAR wipes. Anything above it is toolbar and must
# survive the wipe.
CANVAS_TOP = 67

# Structuring element for the morphological clean-up of the mask. A 5x5 square
# is a good compromise: large enough to kill webcam speckle, small enough to
# leave a fingertip-sized blob intact.
KERNEL = np.ones((5, 5), np.uint8)

# Starting HSV thresholds, tuned for a blue-ish object under indoor light. The
# trackbars let you re-tune at runtime without editing this file.
DEFAULT_HSV = {
    "Upper Hue": 136, "Upper Saturation": 255, "Upper Value": 255,
    "Lower Hue": 100, "Lower Saturation": 83,  "Lower Value": 84,
}

CONTROLS_WINDOW = "Color detectors"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def setValues(x):
    """No-op callback required by ``cv.createTrackbar``.

    OpenCV demands a callback even when you intend to poll the slider yourself
    with ``getTrackbarPos`` - which is exactly what the main loop does - so
    this deliberately does nothing.
    """
    print("")


def draw_toolbar(canvas):
    """Paint the button strip onto ``canvas`` and return it.

    Called once for the paint canvas and again for every camera frame, so the
    buttons stay visible and always line up with the hit-testing in the main
    loop.
    """
    for button in BUTTONS:
        canvas = cv.rectangle(
            canvas,
            (button["x1"], 1),
            (button["x2"], TOOLBAR_HEIGHT),
            button["fill"],
            -1,  # negative thickness means "fill the rectangle"
        )
        if button["label"]:
            cv.putText(
                canvas, button["label"], (button["x1"] + 14, 33),
                cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv.LINE_AA,
            )
    return canvas


def new_stroke_buffers():
    """Return a fresh, empty stroke list for each of the four colours."""
    return (
        [deque(maxlen=TRAIL_LENGTH)],  # blue
        [deque(maxlen=TRAIL_LENGTH)],  # green
        [deque(maxlen=TRAIL_LENGTH)],  # red
        [deque(maxlen=TRAIL_LENGTH)],  # yellow
    )


# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #

# Trackbar panel for live HSV tuning. Hue runs 0-180 in OpenCV (half the usual
# 0-360 degrees, so it fits in one byte); saturation and value run 0-255.
cv.namedWindow(CONTROLS_WINDOW)
for name, default in DEFAULT_HSV.items():
    maximum = 180 if name.endswith("Hue") else 255
    cv.createTrackbar(name, CONTROLS_WINDOW, default, maximum, setValues)

# One list of strokes per colour, plus the index of the stroke currently being
# drawn in each list.
bpoints, gpoints, rpoints, ypoints = new_stroke_buffers()
blue_index = green_index = red_index = yellow_index = 0

# Currently selected brush colour, as an index into COLORS.
colorIndex = 0

# The standalone canvas: a white image that holds the artwork on its own, so it
# stays readable even when the camera feed behind it is busy.
paintWindow = np.zeros(CANVAS_SIZE, dtype=np.uint8) + 255
paintWindow = draw_toolbar(paintWindow)

cap = cv.VideoCapture(0)
cv.namedWindow("Live Drawing", cv.WINDOW_NORMAL)
cv.resizeWindow("Live Drawing", 1280, 720)


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #

while True:
    Success, frame = cap.read()
    if not Success:
        # Camera unplugged, in use by another app, or end of stream.
        break

    # Mirror the frame so the on-screen pointer follows your hand naturally.
    frame = cv.flip(frame, 1)
    hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)

    # Re-read the sliders every frame so tuning takes effect immediately.
    u_hue = cv.getTrackbarPos("Upper Hue", CONTROLS_WINDOW)
    u_saturation = cv.getTrackbarPos("Upper Saturation", CONTROLS_WINDOW)
    u_value = cv.getTrackbarPos("Upper Value", CONTROLS_WINDOW)

    l_hue = cv.getTrackbarPos("Lower Hue", CONTROLS_WINDOW)
    l_saturation = cv.getTrackbarPos("Lower Saturation", CONTROLS_WINDOW)
    l_value = cv.getTrackbarPos("Lower Value", CONTROLS_WINDOW)

    Upper_hsv = np.array([u_hue, u_saturation, u_value])
    Lower_hsv = np.array([l_hue, l_saturation, l_value])

    # Draw the buttons onto the live feed too, so the user can see what they
    # are reaching for.
    frame = draw_toolbar(frame)

    # --- Isolate the pen ---------------------------------------------------
    # inRange produces a binary mask: white where the pixel falls inside the
    # HSV window, black everywhere else.
    mask = cv.inRange(hsv, Lower_hsv, Upper_hsv)
    mask = cv.erode(mask, KERNEL, iterations=1)           # shrink speckles away
    mask = cv.morphologyEx(mask, cv.MORPH_OPEN, KERNEL)   # erode+dilate: clear leftovers
    mask = cv.dilate(mask, KERNEL, iterations=1)          # restore the blob's size

    # RETR_EXTERNAL keeps only outer contours (holes inside the blob are noise
    # here); CHAIN_APPROX_SIMPLE stores corner points instead of every pixel.
    cnts, _ = cv.findContours(mask.copy(), cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

    center = None

    if len(cnts) > 0:
        # The largest blob is assumed to be the pen; smaller ones are clutter
        # that happens to share its colour.
        cnt = sorted(cnts, key=cv.contourArea, reverse=True)[0]
        ((x, y), radius) = cv.minEnclosingCircle(cnt)
        cv.circle(frame, ((int(x), int(y))), int(radius), (0, 255, 255), 2)

        # Image moments give the centroid: m10/m00 and m01/m00 are the mean x
        # and y of the blob's pixels. m00 is the area, so a zero there means a
        # degenerate contour and has to be guarded against before dividing.
        M = cv.moments(cnt)
        if M["m00"] != 0:
            center = (int(M['m10'] / M['m00']), int(M['m01'] / M['m00']))

    if center is not None:
        if center[1] <= TOOLBAR_HEIGHT:
            # --- Pen is over the toolbar: treat it as a button press --------
            if 40 <= center[0] <= 140:
                # CLEAR: drop every stroke and repaint the canvas white from
                # CANVAS_TOP down, leaving the buttons intact.
                bpoints, gpoints, rpoints, ypoints = new_stroke_buffers()
                blue_index = green_index = red_index = yellow_index = 0
                paintWindow[CANVAS_TOP:, :, :] = 255
            elif 160 <= center[0] <= 255:
                colorIndex = 0  # blue
            elif 275 <= center[0] <= 370:
                colorIndex = 1  # green
            elif 390 <= center[0] <= 485:
                colorIndex = 2  # red
            elif 505 <= center[0] <= 600:
                colorIndex = 3  # yellow
        else:
            # --- Pen is on the canvas: extend the current stroke ------------
            # appendleft keeps the newest point at index 0. The render loop
            # below only cares that neighbours are adjacent, so either end of
            # the deque works.
            if colorIndex == 0:
                bpoints[blue_index].appendleft(center)
            elif colorIndex == 1:
                gpoints[green_index].appendleft(center)
            elif colorIndex == 2:
                rpoints[red_index].appendleft(center)
            elif colorIndex == 3:
                ypoints[yellow_index].appendleft(center)
    else:
        # --- "Pen up" ------------------------------------------------------
        # Nothing coloured is in view, so open a new empty stroke for every
        # colour. Without this, lifting the pen and putting it down somewhere
        # else would connect the two positions with one long line.
        bpoints.append(deque(maxlen=TRAIL_LENGTH))
        blue_index += 1
        gpoints.append(deque(maxlen=TRAIL_LENGTH))
        green_index += 1
        rpoints.append(deque(maxlen=TRAIL_LENGTH))
        red_index += 1
        ypoints.append(deque(maxlen=TRAIL_LENGTH))
        yellow_index += 1

    # --- Render every stroke ----------------------------------------------
    # i -> colour, j -> stroke within that colour, k -> point within the
    # stroke. Each pair of consecutive points becomes a short line segment,
    # which is what makes the trail look continuous rather than dotted.
    points = [bpoints, gpoints, rpoints, ypoints]
    for i in range(len(points)):
        for j in range(len(points[i])):
            for k in range(1, len(points[i][j])):
                if points[i][j][k - 1] is None or points[i][j][k] is None:
                    continue
                cv.line(frame, points[i][j][k - 1], points[i][j][k], COLORS[i], 2)
                cv.line(paintWindow, points[i][j][k - 1], points[i][j][k], COLORS[i], 2)

    cv.imshow("Live Drawing", frame)   # camera feed with the drawing overlaid
    cv.imshow("Paint", paintWindow)    # the artwork on its own
    cv.imshow("Mask", mask)            # tuning aid: your object should be white

    # waitKey(1) both pumps the GUI event loop and polls the keyboard; the
    # & 0xff masks off high bits that some platforms set on the key code.
    if cv.waitKey(1) & 0xff == ord('q'):
        break

# Always hand the camera back to the OS and tear the windows down.
cap.release()
cv.destroyAllWindows()
