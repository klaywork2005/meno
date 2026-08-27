# Meno — Air Canvas

Draw in the air. **Meno** turns any coloured object — a bottle cap, a marker
lid, a sticky note on your fingertip — into a paintbrush for your webcam. There
is no mouse and no touchscreen: the program tracks the object frame by frame and
lays down a stroke wherever it moves.

Built with Python, OpenCV and NumPy in ~300 lines, with no machine-learning
model and no training data — just classical computer vision running in real time.

<!-- Add a demo GIF here once recorded, e.g.:
![Demo](docs/demo.gif)
-->

---

## Features

- **Real-time colour tracking** — segments the pen object in HSV space and
  follows the centroid of the largest matching blob.
- **Live HSV tuning** — six trackbars let you re-tune the colour thresholds
  while the program runs, so it adapts to any object and any lighting.
- **Gesture-driven toolbar** — hover the pen over the strip at the top of the
  frame to switch colour or clear the canvas. No keyboard needed while drawing.
- **Four-colour palette** — blue, green, red and yellow, each with its own
  independent stroke history.
- **Pen-up detection** — moving the object out of frame ends the current stroke,
  so separate strokes never get joined by a stray connecting line.
- **Three synchronised views** — the live camera feed with the drawing overlaid,
  a clean paint canvas, and the raw binary mask for debugging your thresholds.

---

## How it works

Each frame runs through the same six-stage pipeline:

| # | Stage | What happens |
|---|-------|--------------|
| 1 | **Capture & mirror** | Read a frame from the webcam and flip it horizontally, so moving your hand right moves the pointer right. |
| 2 | **Colour segmentation** | Convert BGR → HSV and `inRange()` against the trackbar bounds. HSV separates *hue* from *brightness*, which makes thresholding far more tolerant of changing light than raw BGR. |
| 3 | **Noise removal** | Erode → morphological open → dilate with a 5×5 kernel. Speckles vanish; the real blob keeps its original size. |
| 4 | **Blob tracking** | `findContours()` with `RETR_EXTERNAL`, take the largest contour by area, then use image moments (`m10/m00`, `m01/m00`) to get its centroid — the pen tip for this frame. |
| 5 | **Interpret** | If the tip is inside the top 65 px it is a button press (clear / pick a colour); otherwise the point joins the stroke currently being drawn. |
| 6 | **Render** | Replay every stored stroke as connected line segments onto both the camera feed and the paint canvas. |

### Stroke storage

Points are stored as one `deque` per stroke, grouped into one list per colour:

```python
bpoints = [deque_of_stroke_0, deque_of_stroke_1, ...]
```

A `deque` with `maxlen` bounds the memory a long session can use — old points
fall off the tail automatically. When the pen leaves the frame, a fresh deque is
pushed onto each list and the matching index is bumped; that "pen up" event is
what keeps two separate strokes from being connected by one long straight line.

---

## Quick start

**Requirements:** Python 3.9+ and a webcam.

```bash
# 1. Clone
git clone https://github.com/klaywork2005/meno.git
cd meno

# 2. Create a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

Four windows open: **Live Drawing**, **Paint**, **Mask** and **Color detectors**.

---

## Using it

### 1. Tune the colour first

Hold your object in front of the camera and look at the **Mask** window. Adjust
the six trackbars until your object is the *only* solid white shape there:

- **Hue** — which colour you are chasing (0–180 in OpenCV, i.e. half of the
  usual 0–360°). Set the lower/upper pair to bracket your object's hue.
- **Saturation** — how vivid the colour is. Raise the *lower* bound to reject
  washed-out greys and skin tones.
- **Value** — how bright it is. Raise the *lower* bound to reject shadows.

The defaults are tuned for a **blue** object under indoor light.

### 2. Draw

| Action | How |
|--------|-----|
| Draw | Move the object anywhere below the toolbar strip |
| Change colour | Hover over the blue / green / red / yellow box |
| Clear the canvas | Hover over the **CLEAR** box |
| End a stroke | Move the object out of frame (or out of the colour range) |
| Quit | Press <kbd>q</kbd> with any window focused |

---

## Project structure

```
meno/
├── main.py            # The entire application: config, helpers, capture loop
├── requirements.txt   # Pinned runtime dependencies
├── .gitignore         # Keeps .venv/ and __pycache__/ out of version control
├── LICENSE            # MIT
└── README.md
```

`main.py` is organised into four labelled sections:

1. **Configuration** — palette, toolbar layout, kernel size, HSV defaults. Every
   magic number lives here rather than being scattered through the loop.
2. **Helpers** — `draw_toolbar()`, `new_stroke_buffers()` and the trackbar
   callback OpenCV requires.
3. **Setup** — build the trackbar panel, allocate the stroke buffers and the
   canvas, open the camera.
4. **Main loop** — the per-frame pipeline described above.

---

## Design notes

- **Why HSV and not BGR?** In BGR, "blue" changes numerically the moment a cloud
  passes the window, because all three channels carry brightness. HSV puts
  brightness in a single channel (`value`), so a hue range stays valid across a
  much wider set of lighting conditions.
- **Why the largest contour?** Cheap and effective: anything else sharing the
  target colour is usually smaller and further away. It fails gracefully — if a
  bigger object of that colour enters the frame, the pointer simply jumps, and
  tightening the saturation bound fixes it.
- **Why moments instead of the bounding-box centre?** The centroid is stable
  under rotation and partial occlusion; a bounding box jitters as the silhouette
  changes shape.
- **Why one stroke list per colour?** It keeps rendering trivial (loop colour →
  stroke → point) and makes the *clear* action a single reset instead of a
  filtered delete.

---

## Known limitations & possible next steps

- Only one pen is tracked at a time — the largest blob wins.
- The `Paint` window is display-only; there is no "save as PNG" yet
  (`cv.imwrite("drawing.png", paintWindow)` would be the one-liner).
- The toolbar coordinates assume a 640-px-wide frame; a non-standard webcam
  resolution shifts the buttons relative to the video.
- Hover-to-click has no dwell timer, so passing the pen across the toolbar on
  the way somewhere else can trigger a button.
- Natural extensions: adjustable brush thickness, an undo stack, saving/loading
  artwork, and swapping colour tracking for a hand-landmark model such as
  MediaPipe.

---

## License

Released under the [MIT License](LICENSE).
